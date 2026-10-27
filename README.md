# Vaultline Security Audit Grant Protocol & Automated Pre-Audit Suite

A decentralized, trust-minimized grant escrow and pre-audit diagnostic protocol designed specifically for **Colosseum Hackathon Projects** applying for **Vaultline Security Audit Grants** (up to 4,000 USDC per project).

---

## 1. Executive Summary & Overview

Colosseum hackathons (Renaissance, Radar, Breakout) produce high-velocity Solana protocols. However, transitioning from hackathon demo to production mainnet requires rigorous smart contract security verification. Professional smart contract audits often pose prohibitive upfront costs for early-stage builders.

**Vaultline** offers security audit grants of up to **4,000 USDC** per qualifying Colosseum project. This repository provides:
1. **On-Chain Audit Grant Program (`vaultline-grant-protocol`)**: A Solana Anchor smart contract managing grant pool deposits, project grant applications, auditor milestone escrow, verification of audit report commitments (IPFS hashes + SHA256 digests), and non-custodial milestone-based disbursements.
2. **Automated Pre-Audit Static Triage Engine (`pre_audit_scanner.ts`)**: A developer static-analysis harness targeting common Solana/Anchor vulnerabilities (unvalidated account owners, missing signer checks, arbitrary CPI invocation, PDA seed collisions, integer overflow risks) to ensure Colosseum projects maximize the value of their 4,000 USDC grant allocation before human auditors engage.
3. **End-to-End Test Suite**: Complete automated integration tests simulating the grant lifecycle from application to disbursement.

---

## 2. Architecture & On-Chain State Machine

### 2.1 State Lifecycle
```text
[ Colosseum Project Team ]
           |
           v
  1. Initialize Grant Pool (Vaultline Admin: USDC Capitalization)
           |
           v
  2. Apply for Grant (Project Team: Repo, Commit Hash, Scope, Colosseum Track)
           |
           v
  3. Review & Allocate (Vaultline Lead: Approve Grant, max 4,000 USDC into PDA escrow)
           |
           v
  4. Pre-Audit Diagnostic & Scoping (Automated Scanner identifies AST flags)
           |
           v
  5. Audit Completion & Report Attestation (Auditor submits Findings Digest + IPFS CID)
           |
           v
  6. Milestone Release (USDC disbursed directly to certified Vaultline Security Auditor)
```

### 2.2 Program Accounts and PDAs

- **`ProgramConfig`**: PDA seeded with `["config"]`. Stores Vaultline authority, USDC mint, total grants disbursed, and global active grant counters.
- **`GrantPool`**: PDA seeded with `["grant_pool", config_key]`. Holds USDC reserve from Vaultline treasury.
- **`ProjectApplication`**: PDA seeded with `["project_grant", project_pubkey, colosseum_id]`. Tracks application status (`Submitted`, `Approved`, `AuditInProgress`, `Completed`, `Rejected`, `Revoked`), allocated grant amount (capped at 4,000,000,000 native units = 4,000 USDC at 6 decimals), auditor assignment, and report digests.
- **`GrantEscrowVault`**: PDA token account seeded with `["escrow", project_application_key]`. Isolates funds per approved project until audit delivery sign-off.

---

## 3. Key Technical Features

- **Strict Grant Cap Enforcement**: Hardcoded invariants enforce that no single project allocation can exceed 4,000 USDC (`MAX_GRANT_AMOUNT = 4_000_000_000`).
- **Cryptographic Audit Attestation**: Audit delivery requires recording the immutable Keccak256/SHA256 digest of the final report alongside IPFS multi-hashes on-chain.
- **Safe Spl-Token CPI Transfers**: Utilizes Anchor's `anchor_spl::token::Transfer` via PDA seeds to guarantee atomic escrow funding and clawback protections.
- **Dual-Approval Payout Architecture**: Payout requires verification that the auditor has submitted the report and both Vaultline and the Colosseum project acknowledge receipt.

---

## 4. Repository Structure

```
├── programs/
│   └── vaultline-grants/
│       └── src/
│           ├── errors.rs         # Custom error definitions
│           ├── instructions/     # Instruction handlers (initialize, apply, approve, claim)
│           ├── state.rs          # Account data layouts
│           └── lib.rs            # Program entrypoint
├── scripts/
│   └── pre_audit_scanner.ts      # Automated AST & regex Solana vulnerability scanner
├── tests/
│   └── vaultline-grants.ts       # Full integration test suite (Mocha / Chai)
├── Anchor.toml
└── package.json
```

---

## 5. Setup & Deployment Guide

### Prerequisites
- [Rust](https://www.rust-lang.org/tools/install) (v1.75.0 or later)
- [Solana CLI](https://docs.solana.com/cli/install-solana-cli-tools) (v1.18.0 or later)
- [Node.js](https://nodejs.org/) (v18.x or later) & [Yarn](https://yarnpkg.com/)
- [Anchor CLI](https://www.anchor-lang.com/docs/installation) (v0.29.0 or v0.30.0)

### 1. Build the Smart Contract
```bash
anchor build
```

### 2. Run Local Unit & Integration Tests
```bash
anchor test
```

### 3. Run Pre-Audit Vulnerability Scanner on Colosseum Project
Before submitting the application, run the Vaultline diagnostic triage suite over your Anchor codebase:
```bash
npx ts-node scripts/pre_audit_scanner.ts --target-dir ../your-colosseum-project/programs/
```

### 4. Deploy to Devnet
```bash
solana config set --url https://api.devnet.solana.com
solana airdrop 2
anchor deploy --provider.cluster devnet
```