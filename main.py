// ============================================================================
// FILE: programs/vaultline-grants/src/errors.rs
// ============================================================================

use anchor_lang::prelude::*;

#[error_code]
pub enum VaultlineError {
    #[msg("Grant allocation exceeds maximum allowable limit of 4,000 USDC.")]
    GrantLimitExceeded,

    #[msg("Project application is not in the correct status for this action.")]
    InvalidApplicationStatus,

    #[msg("Unauthorized: Signer is not authorized to execute this instruction.")]
    Unauthorized,

    #[msg("Invalid auditor address provided.")]
    InvalidAuditor,

    #[msg("Report hash cannot be empty.")]
    EmptyReportHash,

    #[msg("IPFS report CID cannot be empty.")]
    EmptyReportCid,

    #[msg("Insufficient pool liquidity for grant disbursement.")]
    InsufficientLiquidity,

    #[msg("Project name exceeds maximum length of 64 characters.")]
    ProjectNameTooLong,

    #[msg("Repository URI exceeds maximum length of 128 characters.")]
    RepoUriTooLong,

    #[msg("Arithmetic overflow detected.")]
    MathOverflow,
}

// ============================================================================
// FILE: programs/vaultline-grants/src/state.rs
// ============================================================================

use anchor_lang::prelude::*;

pub const MAX_GRANT_USDC_AMOUNT: u64 = 4_000_000_000; // 4,000 USDC (6 decimals)
pub const MAX_NAME_LEN: usize = 64;
pub const MAX_URI_LEN: usize = 128;
pub const HASH_LEN: usize = 32;

#[derive(AnchorSerialize, AnchorDeserialize, Clone, Copy, PartialEq, Eq)]
pub enum ApplicationStatus {
    Submitted,
    UnderReview,
    Approved,
    AuditInProgress,
    AuditSubmitted,
    Completed,
    Rejected,
    Revoked,
}

#[account]
pub struct ProgramConfig {
    pub authority: Pubkey,
    pub usdc_mint: Pubkey,
    pub treasury_pool: Pubkey,
    pub total_allocated: u64,
    pub total_disbursed: u64,
    pub active_grants_count: u32,
    pub bump: u8,
}

impl ProgramConfig {
    pub const LEN: usize = 8 + // discriminator
        32 + // authority
        32 + // usdc_mint
        32 + // treasury_pool
        8 +  // total_allocated
        8 +  // total_disbursed
        4 +  // active_grants_count
        1;   // bump
}

#[account]
pub struct ProjectApplication {
    pub project_lead: Pubkey,
    pub assigned_auditor: Pubkey,
    pub colosseum_project_id: [u8; 16],
    pub project_name: String,
    pub repo_url: String,
    pub commit_hash: [u8; 20],
    pub requested_amount: u64,
    pub approved_grant_amount: u64,
    pub status: ApplicationStatus,
    pub report_sha256: [u8; 32],
    pub report_ipfs_cid: String,
    pub bump: u8,
    pub escrow_bump: u8,
}

impl ProjectApplication {
    pub const BASE_LEN: usize = 8 + // discriminator
        32 + // project_lead
        32 + // assigned_auditor
        16 + // colosseum_project_id
        4 + MAX_NAME_LEN + // project_name
        4 + MAX_URI_LEN + // repo_url
        20 + // commit_hash (git sha1)
        8 +  // requested_amount
        8 +  // approved_grant_amount
        1 +  // status enum
        32 + // report_sha256
        4 + 64 + // report_ipfs_cid
        1 +  // bump
        1;   // escrow_bump
}

// ============================================================================
// FILE: programs/vaultline-grants/src/instructions/initialize_config.rs
// ============================================================================

use anchor_lang::prelude::*;
use anchor_spl::token::{Mint, Token, TokenAccount};
use crate::state::ProgramConfig;
use crate::errors::VaultlineError;

#[derive(Accounts)]
pub struct InitializeConfig<'info> {
    #[account(mut)]
    pub authority: Signer<'info>,

    pub usdc_mint: Account<'info, Mint>,

    #[account(
        init,
        payer = authority,
        space = ProgramConfig::LEN,
        seeds = [b"vaultline_config"],
        bump
    )]
    pub config: Account<'info, ProgramConfig>,

    #[account(
        init,
        payer = authority,
        token::mint = usdc_mint,
        token::authority = config,
        seeds = [b"vaultline_treasury", config.key().as_ref()],
        bump
    )]
    pub treasury_pool: Account<'info, TokenAccount>,

    pub system_program: Program<'info, System>,
    pub token_program: Program<'info, Token>,
    pub rent: Sysvar<'info, Rent>,
}

pub fn handle_initialize_config(ctx: Context<InitializeConfig>) -> Result<()> {
    let config = &mut ctx.accounts.config;
    config.authority = ctx.accounts.authority.key();
    config.usdc_mint = ctx.accounts.usdc_mint.key();
    config.treasury_pool = ctx.accounts.treasury_pool.key();
    config.total_allocated = 0;
    config.total_disbursed = 0;
    config.active_grants_count = 0;
    config.bump = ctx.bumps.config;

    msg!("Vaultline Grant Protocol Config Initialized. Treasury: {}", config.treasury_pool);
    Ok(())
}

// ============================================================================
// FILE: programs/vaultline-grants/src/instructions/apply_grant.rs
// ============================================================================

use anchor_lang::prelude::*;
use crate::state::{ProjectApplication, ApplicationStatus, MAX_GRANT_USDC_AMOUNT, MAX_NAME_LEN, MAX_URI_LEN};
use crate::errors::VaultlineError;

#[derive(Accounts)]
#[instruction(colosseum_project_id: [u8; 16])]
pub struct ApplyGrant<'info> {
    #[account(mut)]
    pub project_lead: Signer<'info>,

    #[account(
        init,
        payer = project_lead,
        space = ProjectApplication::BASE_LEN,
        seeds = [b"project_grant", project_lead.key().as_ref(), &colosseum_project_id],
        bump
    )]
    pub application: Account<'info, ProjectApplication>,

    pub system_program: Program<'info, System>,
}

pub fn handle_apply_grant(
    ctx: Context<ApplyGrant>,
    colosseum_project_id: [u8; 16],
    project_name: String,
    repo_url: String,
    commit_hash: [u8; 20],
    requested_amount: u64,
) -> Result<()> {
    require!(project_name.len() <= MAX_NAME_LEN, VaultlineError::ProjectNameTooLong);
    require!(repo_url.len() <= MAX_URI_LEN, VaultlineError::RepoUriTooLong);
    require!(requested_amount <= MAX_GRANT_USDC_AMOUNT, VaultlineError::GrantLimitExceeded);

    let application = &mut ctx.accounts.application;
    application.project_lead = ctx.accounts.project_lead.key();
    application.assigned_auditor = Pubkey::default();
    application.colosseum_project_id = colosseum_project_id;
    application.project_name = project_name;
    application.repo_url = repo_url;
    application.commit_hash = commit_hash;
    application.requested_amount = requested_amount;
    application.approved_grant_amount = 0;
    application.status = ApplicationStatus::Submitted;
    application.report_sha256 = [0u8; 32];
    application.report_ipfs_cid = String::new();
    application.bump = ctx.bumps.application;
    application.escrow_bump = 0;

    msg!("Application registered for project: {}. Requested: {} USDC micro-units", application.project_name, requested_amount);
    Ok(())
}

// ============================================================================
// FILE: programs/vaultline-grants/src/instructions/approve_and_fund.rs
// ============================================================================

use anchor_lang::prelude::*;
use anchor_spl::token::{self, Mint, Token, TokenAccount, Transfer};
use crate::state::{ProgramConfig, ProjectApplication, ApplicationStatus, MAX_GRANT_USDC_AMOUNT};
use crate::errors::VaultlineError;

#[derive(Accounts)]
pub struct ApproveAndFund<'info> {
    #[account(
        mut,
        address = config.authority @ VaultlineError::Unauthorized
    )]
    pub authority: Signer<'info>,

    #[account(
        mut,
        seeds = [b"vaultline_config"],
        bump = config.bump
    )]
    pub config: Account<'info, ProgramConfig>,

    pub usdc_mint: Account<'info, Mint>,

    #[account(
        mut,
        address = config.treasury_pool
    )]
    pub treasury_pool: Account<'info, TokenAccount>,

    #[account(
        mut,
        constraint = application.status == ApplicationStatus::Submitted || application.status == ApplicationStatus::UnderReview @ VaultlineError::InvalidApplicationStatus
    )]
    pub application: Account<'info, ProjectApplication>,

    /// CHECK: Auditor pubkey designated by Vaultline
    pub auditor: UncheckedAccount<'info>,

    #[account(
        init,
        payer = authority,
        token::mint = usdc_mint,
        token::authority = application,
        seeds = [b"grant_escrow", application.key().as_ref()],
        bump
    )]
    pub escrow_vault: Account<'info, TokenAccount>,

    pub system_program: Program<'info, System>,
    pub token_program: Program<'info, Token>,
    pub rent: Sysvar<'info, Rent>,
}

pub fn handle_approve_and_fund(
    ctx: Context<ApproveAndFund>,
    approved_amount: u64,
) -> Result<()> {
    require!(approved_amount <= MAX_GRANT_USDC_AMOUNT, VaultlineError::GrantLimitExceeded);
    require!(ctx.accounts.treasury_pool.amount >= approved_amount, VaultlineError::InsufficientLiquidity);

    let application_key = ctx.accounts.application.key();
    let config = &mut ctx.accounts.config;

    // Transfer from Vaultline treasury to project-specific escrow account
    let config_seeds = &[
        b"vaultline_config".as_ref(),
        &[config.bump],
    ];
    let signer = &[&config_seeds[..]];

    let cpi_accounts = Transfer {
        from: ctx.accounts.treasury_pool.to_account_info(),
        to: ctx.accounts.escrow_vault.to_account_info(),
        authority: config.to_account_info(),
    };
    let cpi_ctx = CpiContext::new_with_signer(
        ctx.accounts.token_program.to_account_info(),
        cpi_accounts,
        signer,
    );
    token::transfer(cpi_ctx, approved_amount)?;

    let app = &mut ctx.accounts.application;
    app.approved_grant_amount = approved_amount;
    app.assigned_auditor = ctx.accounts.auditor.key();
    app.status = ApplicationStatus::AuditInProgress;
    app.escrow_bump = ctx.bumps.escrow_vault;

    config.total_allocated = config.total_allocated
        .checked_add(approved_amount)
        .ok_or(VaultlineError::MathOverflow)?;
    config.active_grants_count = config.active_grants_count
        .checked_add(1)
        .ok_or(VaultlineError::MathOverflow)?;

    msg!("Grant approved & escrowed: {} USDC for project app {}", approved_amount, application_key);
    Ok(())
}

// ============================================================================
// FILE: programs/vaultline-grants/src/instructions/submit_audit_report.rs
// ============================================================================

use anchor_lang::prelude::*;
use crate::state::{ProjectApplication, ApplicationStatus};
use crate::errors::VaultlineError;

#[derive(Accounts)]
pub struct SubmitAuditReport<'info> {
    #[account(
        mut,
        constraint = auditor.key() == application.assigned_auditor @ VaultlineError::Unauthorized
    )]
    pub auditor: Signer<'info>,

    #[account(
        mut,
        constraint = application.status == ApplicationStatus::AuditInProgress @ VaultlineError::InvalidApplicationStatus
    )]
    pub application: Account<'info, ProjectApplication>,
}

pub fn handle_submit_audit_report(
    ctx: Context<SubmitAuditReport>,
    report_sha256: [u8; 32],
    report_ipfs_cid: String,
) -> Result<()> {
    require!(report_sha256 != [0u8; 32], VaultlineError::EmptyReportHash);
    require!(!report_ipfs_cid.trim().is_empty(), VaultlineError::EmptyReportCid);

    let application = &mut ctx.accounts.application;
    application.report_sha256 = report_sha256;
    application.report_ipfs_cid = report_ipfs_cid;
    application.status = ApplicationStatus::AuditSubmitted;

    msg!("Audit findings submitted by auditor. Status transitioned to AuditSubmitted.");
    Ok(())
}

// ============================================================================
// FILE: programs/vaultline-grants/src/instructions/disburse_grant.rs
// ============================================================================

use anchor_lang::prelude::*;
use anchor_spl::token::{self, Mint, Token, TokenAccount, Transfer, CloseAccount};
use crate::state::{ProgramConfig, ProjectApplication, ApplicationStatus};
use crate::errors::VaultlineError;

#[derive(Accounts)]
pub struct DisburseGrant<'info> {
    #[account(
        mut,
        address = config.authority @ VaultlineError::Unauthorized
    )]
    pub authority: Signer<'info>,

    #[account(
        mut,
        seeds = [b"vaultline_config"],
        bump = config.bump
    )]
    pub config: Account<'info, ProgramConfig>,

    #[account(
        mut,
        constraint = application.status == ApplicationStatus::AuditSubmitted @ VaultlineError::InvalidApplicationStatus
    )]
    pub application: Account<'info, ProjectApplication>,

    #[account(
        mut,
        seeds = [b"grant_escrow", application.key().as_ref()],
        bump = application.escrow_bump
    )]
    pub escrow_vault: Account<'info, TokenAccount>,

    #[account(
        mut,
        constraint = auditor_token_account.owner == application.assigned_auditor @ VaultlineError::InvalidAuditor
    )]
    pub auditor_token_account: Account<'info, TokenAccount>,

    pub token_program: Program<'info, Token>,
}

pub fn handle_disburse_grant(ctx: Context<DisburseGrant>) -> Result<()> {
    let application = &ctx.accounts.application;
    let grant_amount = application.approved_grant_amount;

    let project_lead_key = application.project_lead;
    let colosseum_id = application.colosseum_project_id;
    let app_bump = application.bump;

    let app_seeds = &[
        b"project_grant".as_ref(),
        project_lead_key.as_ref(),
        colosseum_id.as_ref(),
        &[app_bump],
    ];
    let signer = &[&app_seeds[..]];

    let transfer_accounts = Transfer {
        from: ctx.accounts.escrow_vault.to_account_info(),
        to: ctx.accounts.auditor_token_account.to_account_info(),
        authority: ctx.accounts.application.to_account_info(),
    };

    let cpi_ctx = CpiContext::new_with_signer(
        ctx.accounts.token_program.to_account_info(),
        transfer_accounts,
        signer,
    );
    token::transfer(cpi_ctx, grant_amount)?;

    // Close escrow account to refund rent lamports to authority
    let close_accounts = CloseAccount {
        account: ctx.accounts.escrow_vault.to_account_info(),
        destination: ctx.accounts.authority.to_account_info(),
        authority: ctx.accounts.application.to_account_info(),
    };
    let close_cpi = CpiContext::new_with_signer(
        ctx.accounts.token_program.to_account_info(),
        close_accounts,
        signer,
    );
    token::close_account(close_cpi)?;

    let app_mut = &mut ctx.accounts.application;
    app_mut.status = ApplicationStatus::Completed;

    let cfg = &mut ctx.accounts.config;
    cfg.total_disbursed = cfg.total_disbursed
        .checked_add(grant_amount)
        .ok_or(VaultlineError::MathOverflow)?;
    cfg.active_grants_count = cfg.active_grants_count.saturating_sub(1);

    msg!("Grant disbursed successfully: {} USDC directly to auditor {}", grant_amount, ctx.accounts.auditor_token_account.owner);
    Ok(())
}

// ============================================================================
// FILE: programs/vaultline-grants/src/instructions/mod.rs
// ============================================================================

pub mod initialize_config;
pub mod apply_grant;
pub mod approve_and_fund;
pub mod submit_audit_report;
pub mod disburse_grant;

pub use initialize_config::*;
pub use apply_grant::*;
pub use approve_and_fund::*;
pub use submit_audit_report::*;
pub use disburse_grant::*;

// ============================================================================
// FILE: programs/vaultline-grants/src/lib.rs
// ============================================================================

use anchor_lang::prelude::*;

pub mod errors;
pub mod instructions;
pub mod state;

use instructions::*;

declare_id!("VLinE9s8V2k4zWc2eJ8Z9mHjS3p5qNxQ1t7Yu2aWc1x");

#[program]
pub mod vaultline_grants {
    use super::*;

    pub fn initialize_config(ctx: Context<InitializeConfig>) -> Result<()> {
        instructions::initialize_config::handle_initialize_config(ctx)
    }

    pub fn apply_grant(
        ctx: Context<ApplyGrant>,
        colosseum_project_id: [u8; 16],
        project_name: String,
        repo_url: String,
        commit_hash: [u8; 20],
        requested_amount: u64,
    ) -> Result<()> {
        instructions::apply_grant::handle_apply_grant(
            ctx,
            colosseum_project_id,
            project_name,
            repo_url,
            commit_hash,
            requested_amount,
        )
    }

    pub fn approve_and_fund(
        ctx: Context<ApproveAndFund>,
        approved_amount: u64,
    ) -> Result<()> {
        instructions::approve_and_fund::handle_approve_and_fund(ctx, approved_amount)
    }

    pub fn submit_audit_report(
        ctx: Context<SubmitAuditReport>,
        report_sha256: [u8; 32],
        report_ipfs_cid: String,
    ) -> Result<()> {
        instructions::submit_audit_report::handle_submit_audit_report(
            ctx,
            report_sha256,
            report_ipfs_cid,
        )
    }

    pub fn disburse_grant(ctx: Context<DisburseGrant>) -> Result<()> {
        instructions::disburse_grant::handle_disburse_grant(ctx)
    }
}

// ============================================================================
// FILE: scripts/pre_audit_scanner.ts
// ============================================================================

import * as fs from "fs";
import * as path from "path";
import * as crypto from "crypto";

interface SecurityFinding {
    severity: "HIGH" | "MEDIUM" | "LOW" | "INFORMATIONAL";
    title: string;
    filePath: string;
    line: number;
    snippet: string;
    remediation: string;
}

export class VaultlinePreAuditScanner {
    private targetDir: string;
    private findings: SecurityFinding[] = [];

    constructor(targetDir: string) {
        this.targetDir = targetDir;
    }

    public run(): { findings: SecurityFinding[]; passed: boolean; digest: string } {
        console.log(`[Vaultline Scanner] Analyzing project smart contracts in: ${this.targetDir}`);
        const files = this.collectRustFiles(this.targetDir);
        let totalHash = crypto.createHash("sha256");

        for (const file of files) {
            const content = fs.readFileSync(file, "utf8");
            totalHash.update(content);
            this.scanFile(file, content);
        }

        const digest = totalHash.digest("hex");
        const highFindings = this.findings.filter((f) => f.severity === "HIGH");

        return {
            findings: this.findings,
            passed: highFindings.length === 0,
            digest,
        };
    }

    private collectRustFiles(dir: string): string[] {
        let results: string[] = [];
        if (!fs.existsSync(dir)) return results;
        const list = fs.readdirSync(dir);
        for (const file of list) {
            const fullPath = path.join(dir, file);
            const stat = fs.statSync(fullPath);
            if (stat && stat.isDirectory()) {
                if (file !== "target" && file !== "node_modules") {
                    results = results.concat(this.collectRustFiles(fullPath));
                }
            } else if (file.endsWith(".rs")) {
                results.push(fullPath);
            }
        }
        return results;
    }

    private scanFile(filePath: string, content: string): void {
        const lines = content.split("\n");

        for (let i = 0; i < lines.length; i++) {
            const line = lines[i];

            // 1. Missing Signer check pattern
            if (line.includes("AccountInfo<'info>") && !line.includes("Signer<'info>")) {
                if (lines[Math.max(0, i - 1)].includes("/// CHECK:")) {
                    // documented unchecked account
                } else {
                    this.findings.push({
                        severity: "MEDIUM",
                        title: "Potential Unchecked AccountInfo without Signer constraint",
                        filePath,
                        line: i + 1,
                        snippet: line.trim(),
                        remediation: "Replace AccountInfo with Signer<'info> or add explicit signer assertion.",
                    });
                }
            }

            // 2. Unchecked arithmetic
            if (line.match(/[a-zA-Z0-9_]+\s*(\+=|-=|\*=)\s*[a-zA-Z0-9_]+/) && !line.includes("checked_") && !line.includes("saturating_")) {
                this.findings.push({
                    severity: "LOW",
                    title: "Direct arithmetic operator without checked_* or saturating_* math",
                    filePath,
                    line: i + 1,
                    snippet: line.trim(),
                    remediation: "Use .checked_add(), .checked_sub(), or .checked_mul() to prevent arithmetic overflows.",
                });
            }

            // 3. Dangerous account closure destination
            if (line.includes("close =") && line.includes("project_lead")) {
                this.findings.push({
                    severity: "INFORMATIONAL",
                    title: "Account close instruction present",
                    filePath,
                    line: i + 1,
                    snippet: line.trim(),
                    remediation: "Verify that close destination cannot be manipulated by an attacker to drain rent.",
                });
            }

            // 4. Missing owner check in manual deserialize
            if (line.includes("try_from_slice") && !content.includes("owner == program_id")) {
                this.findings.push({
                    severity: "HIGH",
                    title: "Manual state deserialization without Account owner check",
                    filePath,
                    line: i + 1,
                    snippet: line.trim(),
                    remediation: "Ensure the account owner equals current program_id prior to deserialization.",
                });
            }
        }
    }
}

// CLI Execution entrypoint
if (require.main === module) {
    const args = process.argv.slice(2);
    const targetIdx = args.indexOf("--target-dir");
    const targetPath = targetIdx !== -1 && args[targetIdx + 1] ? args[targetIdx + 1] : "./programs";

    const scanner = new VaultlinePreAuditScanner(targetPath);
    const result = scanner.run();

    console.log("\n================ VAULTLINE PRE-AUDIT REPORT ================");
    console.log(`Scanned Target: ${targetPath}`);
    console.log(`Codebase SHA-256 Digest: ${result.digest}`);
    console.log(`Audit Readiness Status: ${result.passed ? "READY FOR VAULTLINE GRANT" : "REMEDIATION REQUIRED"}`);
    console.log(`Total Findings: ${result.findings.length}`);
    console.log("============================================================\n");

    for (const finding of result.findings) {
        console.log(`[${finding.severity}] ${finding.title}`);
        console.log(`  File: ${finding.filePath}:${finding.line}`);
        console.log(`  Code: ${finding.snippet}`);
        console.log(`  Fix:  ${finding.remediation}\n`);
    }
}

// ============================================================================
// FILE: tests/vaultline-grants.ts
// ============================================================================

import * as anchor from "@coral-xyz/anchor";
import { Program } from "@coral-xyz/anchor";
import { Keypair, PublicKey, SystemProgram } from "@solana/web3.js";
import {
    TOKEN_PROGRAM_ID,
    createMint,
    createAccount,
    mintTo,
    getAccount,
} from "@solana/spl-token";
import { assert, expect } from "chai";
import * as crypto from "crypto";

describe("vaultline-grants", () => {
    const provider = anchor.AnchorProvider.env();
    anchor.setProvider(provider);

    const program = anchor.workspace.VaultlineGrants as Program<any>;

    const vaultlineAdmin = Keypair.generate();
    const projectLead = Keypair.generate();
    const certifiedAuditor = Keypair.generate();

    let usdcMint: PublicKey;
    let configPda: PublicKey;
    let configBump: number;
    let treasuryPda: PublicKey;

    const colosseumProjectId = Buffer.from("COLOSSEUM_REN_01"); // 16 bytes
    let projectAppPda: PublicKey;
    let escrowVaultPda: PublicKey;

    const GRANT_AMOUNT_4K = new anchor.BN(4_000_000_000); // 4,000 USDC (6 decimals)

    before(async () => {
        // Airdrop SOL to test actors
        for (const actor of [vaultlineAdmin, projectLead, certifiedAuditor]) {
            const sig = await provider.connection.requestAirdrop(
                actor.publicKey,
                5 * anchor.web3.LAMPORTS_PER_SOL
            );
            const latestBlockhash = await provider.connection.getLatestBlockhash();
            await provider.connection.confirmTransaction({
                signature: sig,
                ...latestBlockhash,
            });
        }

        // Create Mock USDC Mint (6 decimals)
        usdcMint = await createMint(
            provider.connection,
            vaultlineAdmin,
            vaultlineAdmin.publicKey,
            null,
            6
        );

        [configPda, configBump] = PublicKey.findProgramAddressSync(
            [Buffer.from("vaultline_config")],
            program.programId
        );

        [treasuryPda] = PublicKey.findProgramAddressSync(
            [Buffer.from("vaultline_treasury"), configPda.toBuffer()],
            program.programId
        );

        [projectAppPda] = PublicKey.findProgramAddressSync(
            [
                Buffer.from("project_grant"),
                projectLead.publicKey.toBuffer(),
                colosseumProjectId,
            ],
            program.programId
        );

        [escrowVaultPda] = PublicKey.findProgramAddressSync(
            [Buffer.from("grant_escrow"), projectAppPda.toBuffer()],
            program.programId
        );
    });

    it("Initializes Vaultline Program Config & Treasury Pool", async () => {
        await program.methods
            .initializeConfig()
            .accounts({
                authority: vaultlineAdmin.publicKey,
                usdcMint: usdcMint,
                config: configPda,
                treasuryPool: treasuryPda,
                systemProgram: SystemProgram.programId,
                tokenProgram: TOKEN_PROGRAM_ID,
                rent: anchor.web3.SYSVAR_RENT_PUBKEY,
            })
            .signers([vaultlineAdmin])
            .rpc();

        const configAccount = await program.account.programConfig.fetch(configPda);
        assert.equal(configAccount.authority.toBase58(), vaultlineAdmin.publicKey.toBase58());
        assert.equal(configAccount.usdcMint.toBase58(), usdcMint.toBase58());
        assert.equal(configAccount.activeGrantsCount, 0);

        // Fund Vaultline Treasury with 50,000 USDC
        await mintTo(
            provider.connection,
            vaultlineAdmin,
            usdcMint,
            treasuryPda,
            vaultlineAdmin,
            50_000_000_000
        );

        const treasuryAccount = await getAccount(provider.connection, treasuryPda);
        assert.equal(Number(treasuryAccount.amount), 50_000_000_000);
    });

    it("Allows a Colosseum Project to Submit an Audit Grant Application", async () => {
        const dummyGitCommit = new Uint8Array(20).fill(7); // Git SHA1

        await program.methods
            .applyGrant(
                Array.from(colosseumProjectId),
                "Colosseum DePIN Protocol",
                "https://github.com/colosseum/project-depin",
                Array.from(dummyGitCommit),
                GRANT_AMOUNT_4K
            )
            .accounts({
                projectLead: projectLead.publicKey,
                application: projectAppPda,
                systemProgram: SystemProgram.programId,
            })
            .signers([projectLead])
            .rpc();

        const appState = await program.account.projectApplication.fetch(projectAppPda);
        assert.equal(appState.projectName, "Colosseum DePIN Protocol");
        assert.equal(appState.requestedAmount.toNumber(), 4_000_000_000);
        assert.deepEqual(appState.status, { submitted: {} });
    });

    it("Rejects Grant Approval that exceeds 4,000 USDC cap", async () => {
        const excessiveAmount = new anchor.BN(4_000_000_001);

        try {
            await program.methods
                .approveAndFund(excessiveAmount)
                .accounts({
                    authority: vaultlineAdmin.publicKey,
                    config: configPda,
                    usdcMint: usdcMint,
                    treasuryPool: treasuryPda,
                    application: projectAppPda,
                    auditor: certifiedAuditor.publicKey,
                    escrowVault: escrowVaultPda,
                    systemProgram: SystemProgram.programId,
                    tokenProgram: TOKEN_PROGRAM_ID,
                    rent: anchor.web3.SYSVAR_RENT_PUBKEY,
                })
                .signers([vaultlineAdmin])
                .rpc();
            assert.fail("Should have failed due to GrantLimitExceeded");
        } catch (err: any) {
            expect(err.error?.errorCode?.code || err.message).to.satisfy((c: string) =>
                c.includes("GrantLimitExceeded") || c.includes("custom program error")
            );
        }
    });

    it("Approves Grant and Escrows exactly 4,000 USDC", async () => {
        await program.methods
            .approveAndFund(GRANT_AMOUNT_4K)
            .accounts({
                authority: vaultlineAdmin.publicKey,
                config: configPda,
                usdcMint: usdcMint,
                treasuryPool: treasuryPda,
                application: projectAppPda,
                auditor: certifiedAuditor.publicKey,
                escrowVault: escrowVaultPda,
                systemProgram: SystemProgram.programId,
                tokenProgram: TOKEN_PROGRAM_ID,
                rent: anchor.web3.SYSVAR_RENT_PUBKEY,
            })
            .signers([vaultlineAdmin])
            .rpc();

        const appState = await program.account.projectApplication.fetch(projectAppPda);
        assert.deepEqual(appState.status, { auditInProgress: {} });
        assert.equal(appState.assignedAuditor.toBase58(), certifiedAuditor.publicKey.toBase58());

        const escrowAccount = await getAccount(provider.connection, escrowVaultPda);
        assert.equal(Number(escrowAccount.amount), 4_000_000_000);
    });

    it("Auditor Submits Cryptographic Report Digest & IPFS CID", async () => {
        const dummySha256 = crypto.createHash("sha256").update("VAULTLINE_FINAL_AUDIT_REPORT").digest();
        const dummyIpfsCid = "QmZtmD2qt8fJv32FNFDjCU5jhtWv2x7dUXo2f6yob24CYp";

        await program.methods
            .submitAuditReport(
                Array.from(dummySha256),
                dummyIpfsCid
            )
            .accounts({
                auditor: certifiedAuditor.publicKey,
                application: projectAppPda,
            })
            .signers([certifiedAuditor])
            .rpc();

        const appState = await program.account.projectApplication.fetch(projectAppPda);
        assert.deepEqual(appState.status, { auditSubmitted: {} });
        assert.equal(appState.reportIpfsCid, dummyIpfsCid);
    });

    it("Disburses 4,000 USDC Grant directly to the Auditor and closes Escrow", async () => {
        const auditorTokenAccount = await createAccount(
            provider.connection,
            certifiedAuditor,
            usdcMint,
            certifiedAuditor.publicKey
        );

        await program.methods
            .disburseGrant()
            .accounts({
                authority: vaultlineAdmin.publicKey,
                config: configPda,
                application: projectAppPda,
                escrowVault: escrowVaultPda,
                auditorTokenAccount: auditorTokenAccount,
                tokenProgram: TOKEN_PROGRAM_ID,
            })
            .signers([vaultlineAdmin])
            .rpc();

        const payoutAccount = await getAccount(provider.connection, auditorTokenAccount);
        assert.equal(Number(payoutAccount.amount), 4_000_000_000);

        const appState = await program.account.projectApplication.fetch(projectAppPda);
        assert.deepEqual(appState.status, { completed: {} });

        const configAccount = await program.account.programConfig.fetch(configPda);
        assert.equal(configAccount.totalDisbursed.toNumber(), 4_000_000_000);
        assert.equal(configAccount.activeGrantsCount, 0);

        // Verify Escrow account has been closed
        const closedAccountInfo = await provider.connection.getAccountInfo(escrowVaultPda);
        assert.isNull(closedAccountInfo);
    });
});

// ============================================================================
// FILE: Anchor.toml
// ============================================================================
/*
[features]
seeds = true
skip-lint = false

[programs.localnet]
vaultline_grants = "VLinE9s8V2k4zWc2eJ8Z9mHjS3p5qNxQ1t7Yu2aWc1x"

[registry]
url = "https://api.apr.dev"

[provider]
cluster = "Localnet"
wallet = "~/.config/solana/id.json"

[scripts]
test = "yarn run ts-mocha -p ./tsconfig.json -t 1000000 tests/**/*.ts"
*/

// ============================================================================
// FILE: package.json
// ============================================================================
/*
{
  "name": "vaultline-colosseum-grants",
  "version": "1.0.0",
  "description": "Vaultline Security Audit Grants Protocol for Colosseum Projects",
  "main": "index.js",
  "scripts": {
    "lint": "prettier --write '**/*.{ts,js,json}'",
    "test": "anchor test",
    "scan": "ts-node scripts/pre_audit_scanner.ts --target-dir programs/"
  },
  "dependencies": {
    "@coral-xyz/anchor": "^0.29.0",
    "@solana/spl-token": "^0.4.0",
    "@solana/web3.js": "^1.89.0"
  },
  "devDependencies": {
    "@types/bn.js": "^5.1.0",
    "@types/chai": "^4.3.0",
    "@types/mocha": "^10.0.0",
    "@types/node": "^20.0.0",
    "chai": "^4.3.4",
    "mocha": "^10.2.0",
    "ts-mocha": "^10.0.0",
    "ts-node": "^10.9.1",
    "typescript": "^5.0.0"
  }
}
*/