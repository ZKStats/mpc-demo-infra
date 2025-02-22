// Runs a simple Prover which connects to the Notary and notarizes a request/response from
// example.com. The Prover then generates a proof and writes it to disk.

use http_body_util::Empty;
use http_body_util::BodyExt;
use hyper::{body::Bytes, Request, StatusCode};
use hyper_util::rt::TokioIo;
use std::ops::Range;
use tlsn_core::{proof::TlsProof, transcript::get_value_ids};
use tokio::io::AsyncWriteExt as _;
use tokio_util::compat::{FuturesAsyncReadCompatExt, TokioAsyncReadCompatExt};
use notary_client::{Accepted, NotarizationRequest, NotaryClient};
use tlsn_examples::run_notary;
use tlsn_prover::tls::{state::Notarize, Prover, ProverConfig};
use mpz_core::commit::Nonce;
use serde_json::json;

// Setting of the application server
const SERVER_DOMAIN: &str = "jernkunpittaya.github.io";
const USER_AGENT: &str = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36";

// P/S: If the following limits are increased, please ensure max-transcript-size of
// the notary server's config (../../../notary/server) is increased too, where
// max-transcript-size = MAX_SENT_DATA + MAX_RECV_DATA
//
// Maximum number of bytes that can be sent from prover to server
const MAX_SENT_DATA: usize = 1 << 12;
// Maximum number of bytes that can be received by prover from server
const MAX_RECV_DATA: usize = 1 << 14;
use std::{env, str};

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt::init();
    // Get party index from command line argument
    let args: Vec<String> = env::args().collect();
    let notary_host = args.get(1).expect("Please provide notary host as first argument");
    let notary_port = args.get(2)
        .expect("Please provide notary port as second argument")
        .parse::<u16>()
        .expect("Port must be a valid number");
    let party_index = match args.get(3) {
        Some(index) => match index.as_str() {
            "0" | "1" | "2" => index,
            _ => {
                eprintln!("Error: Party index must be 0, 1, or 2");
                std::process::exit(1);
            }
        },
        None => {
            eprintln!("Error: Party index not provided");
            std::process::exit(1);
        }
    };
    let notary_crt_path = args.get(6); // optional

    let (prover_socket, notary_socket) = tokio::io::duplex(1 << 16);

    // Start a local simple notary service
    tokio::spawn(run_notary(notary_socket.compat()));

    // Build a client to connect to the notary server.
    let notary_client = NotaryClient::builder()
        .host(notary_host)
        .port(notary_port)
        // WARNING: Always use TLS to connect to notary server, except if notary is running locally
        .enable_tls(true)
        .root_cert_store(build_root_store(&notary_crt_path))
        .build()
        .unwrap();

    // Send requests for configuration and notarization to the notary server.
    let notarization_request = NotarizationRequest::builder()
        .max_sent_data(MAX_SENT_DATA)
        .max_recv_data(MAX_RECV_DATA)
        .build()
        .unwrap();

    let Accepted {
        io: notary_connection,
        id: session_id,
        ..
    } = notary_client
        .request_notarization(notarization_request)
        .await
        .unwrap();

    // Configure a new prover with the unique session id returned from notary client.
    let prover_config = ProverConfig::builder()
        .id(session_id)
        .server_dns(SERVER_DOMAIN)
        .max_sent_data(MAX_SENT_DATA)
        .max_recv_data(MAX_RECV_DATA)
        .build()
        .unwrap();

    // Create a new prover and set up the MPC backend.
    let prover = Prover::new(prover_config)
        .setup(notary_connection.compat())
        .await
        .unwrap();


    // Connect to the Server via TCP. This is the TLS client socket.
    let client_socket = tokio::net::TcpStream::connect((SERVER_DOMAIN, 443))
        .await
        .unwrap();

    // Bind the Prover to the server connection.
    // The returned `mpc_tls_connection` is an MPC TLS connection to the Server: all data written
    // to/read from it will be encrypted/decrypted using MPC with the Notary.
    let (mpc_tls_connection, prover_fut) = prover.connect(client_socket.compat()).await.unwrap();
    let mpc_tls_connection = TokioIo::new(mpc_tls_connection.compat());

    // Spawn the Prover task to be run concurrently
    let prover_task = tokio::spawn(prover_fut);

    // Attach the hyper HTTP client to the MPC TLS connection
    let (mut request_sender, connection) =
        hyper::client::conn::http1::handshake(mpc_tls_connection)
            .await
            .unwrap();

    // Spawn the HTTP task to be run concurrently
    tokio::spawn(connection);

    // Build a simple HTTP request with common headers
    let request = Request::builder()
        .uri(format!("/followers-page/party_{}.html", party_index))
        .header("Host", SERVER_DOMAIN)
        .header("Accept", "*/*")
        // Using "identity" instructs the Server not to use compression for its HTTP response.
        // TLSNotary tooling does not support compression.
        .header("Accept-Encoding", "identity")
        .header("Connection", "close")
        .header("User-Agent", USER_AGENT)
        .body(Empty::<Bytes>::new())
        .unwrap();

    println!("Starting an MPC TLS connection with the server");

    // Send the request to the Server and get a response via the MPC TLS connection
    let response = request_sender.send_request(request).await.unwrap();

    println!("Got a response from the server");

    assert!(response.status() == StatusCode::OK);

    // Read and print the response body
    let body_bytes = response.into_body().collect().await.unwrap().to_bytes();
    let body_str = String::from_utf8_lossy(&body_bytes);

    println!("Response body:\n{}", body_str);

    // Extract followers count
    let followers_count = body_str
        .lines()
        .find(|line| line.starts_with("followers="))
        .and_then(|line| line.split('=').nth(1))
        // .and_then(|count| count.parse::<f32>().ok())
        .ok_or_else(|| {
            eprintln!("Error: Followers count not found in the response");
            std::process::exit(1);
        })
        .unwrap();

    println!("Party {} has {} followers", party_index, followers_count);

    // The Prover task should be done now, so we can grab the Prover.
    let prover = prover_task.await.unwrap().unwrap();

    // Prepare for notarization.
    let prover = prover.start_notarize();

    // Build proof (with or without redactions)
    let redact = true;
    let (proof, nonce) = if !redact {
        (build_proof_without_redactions(prover).await, None)
    } else {
        build_proof_with_redactions(prover).await
    };

    // Write the proof to a file
    let file_dest = args.get(4).expect("Please provide a file destination as the second argument");
    let mut file = tokio::fs::File::create(file_dest).await.unwrap();
    file.write_all(serde_json::to_string_pretty(&proof).unwrap().as_bytes())
        .await
        .unwrap();
    if nonce.is_none(){
        println!("No redaction, no need to write to secret file");
    }
    else{
        let secret_file_dest = args.get(5).expect("Please provide a file destination for secret values as the third argument");
        let mut secret_file = tokio::fs::File::create(secret_file_dest).await.unwrap();
        let data = json!({
            "follower": followers_count,
            "nonce": nonce.unwrap()
        });
        let json_string = serde_json::to_string_pretty(&data).unwrap();

        // Write the JSON string to a secret file
        secret_file.write_all(json_string.as_bytes()).await.unwrap();
    }
    println!("Notarization completed successfully!");
}

/// Find the ranges of the public and private parts of a sequence.
///
/// Returns a tuple of `(public, private)` ranges.
fn find_ranges(seq: &[u8], private_seq: &[&[u8]]) -> (Vec<Range<usize>>, Vec<Range<usize>>) {
    let mut private_ranges = Vec::new();
    for s in private_seq {
        for (idx, w) in seq.windows(s.len()).enumerate() {
            if w == *s {
                private_ranges.push(idx..(idx + w.len()));
            }
        }
    }

    let mut sorted_ranges = private_ranges.clone();
    sorted_ranges.sort_by_key(|r| r.start);

    let mut public_ranges = Vec::new();
    let mut last_end = 0;
    for r in sorted_ranges {
        if r.start > last_end {
            public_ranges.push(last_end..r.start);
        }
        last_end = r.end;
    }

    if last_end < seq.len() {
        public_ranges.push(last_end..seq.len());
    }

    (public_ranges, private_ranges)
}
// Function to find ranges using regex
fn find_ranges_regex(seq: &[u8], private_regexes: &[&str]) -> (Vec<Range<usize>>, Vec<Range<usize>>) {
    use regex::bytes::Regex;

    let mut private_ranges = Vec::new();

    for private_regex in private_regexes {
        let re = Regex::new(private_regex).unwrap();
        for cap in re.captures_iter(seq) {
            if let Some(private_part) = cap.get(1) {
                private_ranges.push(private_part.range());
            }
        }
    }

    let mut sorted_ranges = private_ranges.clone();
    sorted_ranges.sort_by_key(|r| r.start);

    let mut public_ranges = Vec::new();
    let mut last_end = 0;
    for r in sorted_ranges {
        if r.start > last_end {
            public_ranges.push(last_end..r.start);
        }
        last_end = r.end;
    }

    if last_end < seq.len() {
        public_ranges.push(last_end..seq.len());
    }

    (public_ranges, private_ranges)
}

async fn build_proof_without_redactions(mut prover: Prover<Notarize>) -> TlsProof {
    let sent_len = prover.sent_transcript().data().len();
    let recv_len = prover.recv_transcript().data().len();

    let builder = prover.commitment_builder();
    let sent_commitment = builder.commit_sent(&(0..sent_len)).unwrap();
    let recv_commitment = builder.commit_recv(&(0..recv_len)).unwrap();

    // Finalize, returning the notarized session
    let notarized_session = prover.finalize().await.unwrap();

    // Create a proof for all committed data in this session
    let mut proof_builder = notarized_session.data().build_substrings_proof();

    // Reveal all the public ranges
    proof_builder.reveal_by_id(sent_commitment).unwrap();
    proof_builder.reveal_by_id(recv_commitment).unwrap();

    let substrings_proof = proof_builder.build().unwrap();

    TlsProof {
        session: notarized_session.session_proof(),
        substrings: substrings_proof,
        //Ignoring because no redactions, thus no private ranges
        encodings: Vec::new(),
    }
}

async fn build_proof_with_redactions(mut prover: Prover<Notarize>) -> (TlsProof, Option<Nonce>) {
    // Identify the ranges in the outbound data which contain data which we want to disclose
    let (sent_public_ranges, _) = find_ranges(
        prover.sent_transcript().data(),
        &[
            // Redact the value of the "User-Agent" header. It will NOT be disclosed.
            USER_AGENT.as_bytes(),
        ],
    );

    // Identify the ranges in the inbound data which contain data which we want to disclose
    let (recv_public_ranges, recv_private_ranges) = find_ranges_regex(
        prover.recv_transcript().data(),
        &[r"followers=(\d+(\.\d+)?)"],
    );
    println!("Received private ranges: {:?}", recv_private_ranges);

    let builder = prover.commitment_builder();

    // Commit to each range of the public outbound data which we want to disclose
    let sent_commitments: Vec<_> = sent_public_ranges
        .iter()
        .map(|range| builder.commit_sent(range).unwrap())
        .collect();
    // Commit to each range of the public inbound data which we want to disclose
    let recv_commitments: Vec<_> = recv_public_ranges
        .iter()
        .map(|range| builder.commit_recv(range).unwrap())
        .collect();

    println!("Committing to private ranges");
    let recv_private_commitments: Vec<_> = recv_private_ranges
        .iter()
        .map(|range| {
            println!("Committing to private range {:?}", range);
            builder.commit_recv(range).unwrap()
        })
        .collect();

    // Finalize, returning the notarized session
    let notarized_session = prover.finalize().await.unwrap();

    // Create a proof for all committed data in this session
    let mut proof_builder = notarized_session.data().build_substrings_proof();

    // Reveal all the public ranges
    for commitment_id in sent_commitments {
        proof_builder.reveal_by_id(commitment_id).unwrap();
    }
    for commitment_id in recv_commitments {
        proof_builder.reveal_by_id(commitment_id).unwrap();
    }

    // for commitment_id in recv_private_commitments {
    //     println!("Revealing private commitment {:?}", commitment_id);
    //     proof_builder.reveal_private_by_id(commitment_id).await.unwrap();
    // }

    // Here only support revealing one private_commitment (if multiple can modify to use for-loop as shown above)
    let commitment_id = recv_private_commitments[0];
    println!("Revealing private commitment {:?}", commitment_id);
    let nonce = proof_builder.reveal_private_by_id(commitment_id).await.unwrap();
    let substrings_proof = proof_builder.build().unwrap();
    // [712..724]
    println!("Received private ranges: {:?}", recv_private_ranges);
    // Generate the encodings for the private ranges
    // Value ids: ["rx/712", "rx/713", "rx/714", "rx/715", "rx/716", "rx/717", "rx/718", "rx/719", "rx/720", "rx/721", "rx/722", "rx/723"]
    // received_private_encodings len: 12
    let received_private_encodings =
        get_value_ids(&recv_private_ranges.into(), tlsn_core::Direction::Received)
            .map(|id| notarized_session.header().encode(&id))
            .collect::<Vec<_>>();

    (TlsProof {
        session: notarized_session.session_proof(),
        substrings: substrings_proof,
        encodings: received_private_encodings,
    }, Some(nonce))
}


use std::{
    fs::File,
    io::BufReader,
  };
  use rustls::{Certificate, OwnedTrustAnchor, RootCertStore};
  use rustls_pemfile::certs;
  
  fn build_root_store(notary_crt_path: &Option<&String>) -> RootCertStore {
      let mut root_store = RootCertStore::empty();
      root_store.add_trust_anchors(webpki_roots::TLS_SERVER_ROOTS.iter().map(|ta| {
          OwnedTrustAnchor::from_subject_spki_name_constraints(
              ta.subject.as_ref(),
              ta.subject_public_key_info.as_ref(),
              ta.name_constraints.as_ref().map(|nc| nc.as_ref()),
          )
      }));
  
      if let Some(notary_crt_path) = notary_crt_path {
          if let Ok(f) = File::open(notary_crt_path) {
              let mut reader = BufReader::new(f);
              if let Ok(xs) = certs(&mut reader) {
                  for x in xs {
                      match root_store.add(&Certificate(x.clone())) {
                        Ok(_) => print!("Added cert: {:?}", x),
                        Err(err) => panic!("Failed load cert: {}", err),
                      }
                  }
              } else {
                  panic!("Failed to load certificates from file");
              }
          } else {
              panic!("Failed to open file: {}", notary_crt_path);
          }
      }
      root_store
  }