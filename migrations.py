# the migration file is where you build your database tables
# If you create a new release for your extension ,
# remember the migration file is like a blockchain, never edit only add!


async def m001_initial(db):
    """
    Initial templates table.
    """
    await db.execute("""
        CREATE TABLE satshole.maintable (
            id TEXT PRIMARY KEY NOT NULL,
            wallet TEXT NOT NULL,
            name TEXT NOT NULL,
            total INTEGER DEFAULT 0,
            lnurlpayamount INTEGER DEFAULT 0,
            lnurlwithdrawamount INTEGER DEFAULT 0
        );
    """)


async def m002_add_timestamp(db):
    """
    Add timestamp to templates table.
    """
    await db.execute(f"""
        ALTER TABLE satshole.maintable
        ADD COLUMN created_at TIMESTAMP NOT NULL DEFAULT {db.timestamp_now};
    """)


async def m003_game_runs(db):
    await db.execute("""CREATE TABLE IF NOT EXISTS satshole.game_settings (
        id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, wallet_id TEXT NOT NULL,
        config TEXT NOT NULL
    )""")
    await db.execute("""CREATE TABLE IF NOT EXISTS satshole.players (
        id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE,
        display_name TEXT NOT NULL, free_used INTEGER NOT NULL DEFAULT 0,
        blocked INTEGER NOT NULL DEFAULT 0, created_at BIGINT NOT NULL
    )""")
    await db.execute("""CREATE TABLE IF NOT EXISTS satshole.runs (
        id TEXT PRIMARY KEY, player_id TEXT NOT NULL, wallet_id TEXT,
        status TEXT NOT NULL, paid INTEGER NOT NULL DEFAULT 0,
        amount INTEGER NOT NULL, payment_hash TEXT UNIQUE, bolt11 TEXT,
        game_version TEXT NOT NULL, map_version TEXT NOT NULL,
        config TEXT NOT NULL, seed BIGINT NOT NULL,
        created_at BIGINT NOT NULL, expires_at BIGINT NOT NULL,
        started_at BIGINT, finished_at BIGINT, verified_at BIGINT,
        token_hash TEXT, input_hash TEXT, input_log TEXT,
        authoritative_score BIGINT, result TEXT
    )""")
    await db.execute("""CREATE TABLE IF NOT EXISTS satshole.financial_events (
        id TEXT PRIMARY KEY, kind TEXT NOT NULL, payment_hash TEXT NOT NULL,
        player_id TEXT NOT NULL, run_id TEXT NOT NULL,
        amount BIGINT NOT NULL, created_at BIGINT NOT NULL
    )""")
    if db.type == "SQLITE":
        await db.execute(
            """CREATE INDEX IF NOT EXISTS satshole.runs_player ON runs (player_id,
        created_at)"""
        )
    else:
        await db.execute(
            """CREATE INDEX IF NOT EXISTS runs_player ON satshole.runs (player_id,
        created_at)"""
        )


async def m004_competitions(db):
    await db.execute("""CREATE TABLE satshole.competitions (
        id TEXT PRIMARY KEY, starts_at BIGINT NOT NULL, ends_at BIGINT NOT NULL,
        status TEXT NOT NULL, config TEXT NOT NULL, wallet_id TEXT NOT NULL,
        UNIQUE(ends_at)
    )""")
    await db.execute("ALTER TABLE satshole.runs ADD COLUMN competition_id TEXT")
    await db.execute("""CREATE TABLE satshole.submissions (
        id TEXT PRIMARY KEY, competition_id TEXT NOT NULL, player_id TEXT NOT NULL,
        run_id TEXT NOT NULL UNIQUE, wallet_id TEXT NOT NULL,
        payout_address TEXT NOT NULL, display_name TEXT NOT NULL,
        amount BIGINT NOT NULL, prize_contribution BIGINT NOT NULL,
        operator_contribution BIGINT NOT NULL, status TEXT NOT NULL,
        payment_hash TEXT UNIQUE, bolt11 TEXT, created_at BIGINT NOT NULL,
        expires_at BIGINT NOT NULL
    )""")
    await db.execute(f"""CREATE TABLE satshole.competition_events (
        seq {db.serial_primary_key}, id TEXT NOT NULL UNIQUE,
        kind TEXT NOT NULL, competition_id TEXT NOT NULL,
        submission_id TEXT NOT NULL UNIQUE, player_id TEXT NOT NULL,
        run_id TEXT NOT NULL, payment_hash TEXT NOT NULL UNIQUE,
        amount BIGINT NOT NULL, prize_contribution BIGINT NOT NULL,
        operator_contribution BIGINT NOT NULL, refund_liability BIGINT NOT NULL,
        created_at BIGINT NOT NULL
    )""")


async def m005_entry_invoice_attempts(db):
    await db.execute("""CREATE TABLE satshole.entry_invoices (
        id TEXT PRIMARY KEY, submission_id TEXT NOT NULL,
        status TEXT NOT NULL, payment_hash TEXT UNIQUE, bolt11 TEXT,
        created_at BIGINT NOT NULL, expires_at BIGINT NOT NULL
    )""")
    await db.execute("""CREATE TABLE satshole.entry_overpayments (
        payment_hash TEXT PRIMARY KEY, competition_id TEXT NOT NULL,
        submission_id TEXT NOT NULL, player_id TEXT NOT NULL,
        run_id TEXT NOT NULL, amount BIGINT NOT NULL, created_at BIGINT NOT NULL
    )""")


async def m006_settlement(db):
    await db.execute("""CREATE TABLE satshole.settlements (
        competition_id TEXT PRIMARY KEY, plan TEXT NOT NULL, pot BIGINT NOT NULL,
        carry_amount BIGINT NOT NULL, carry_to TEXT NOT NULL, created_at BIGINT NOT NULL
    )""")
    await db.execute("""CREATE TABLE satshole.outgoing (
        id TEXT PRIMARY KEY, kind TEXT NOT NULL, competition_id TEXT NOT NULL,
        wallet_id TEXT NOT NULL,address TEXT NOT NULL,amount BIGINT NOT NULL,
        status TEXT NOT NULL,payment_hash TEXT UNIQUE,bolt11 TEXT,error TEXT,
        created_at BIGINT NOT NULL
    )""")


async def m007_outgoing_receipts(db):
    await db.execute("""CREATE TABLE satshole.outgoing_receipts (
        outgoing_id TEXT PRIMARY KEY, payment_hash TEXT NOT NULL UNIQUE,
        kind TEXT NOT NULL, competition_id TEXT NOT NULL,
        amount BIGINT NOT NULL, fee_msat BIGINT NOT NULL, paid_at BIGINT NOT NULL
    )""")


async def m008_operator_review(db):
    await db.execute("""ALTER TABLE satshole.submissions ADD COLUMN disqualified
        INTEGER NOT NULL DEFAULT 0""")
    await db.execute("ALTER TABLE satshole.settlements ADD COLUMN rankings TEXT")
    await db.execute(
        "ALTER TABLE satshole.outgoing ADD COLUMN held INTEGER NOT NULL DEFAULT 0"
    )
    await db.execute("ALTER TABLE satshole.outgoing ADD COLUMN send_started_at BIGINT")
    # Existing invoices may have been attempted before send markers existed.
    await db.execute("""UPDATE satshole.outgoing SET send_started_at=created_at
        WHERE payment_hash IS NOT NULL""")
    await db.execute(f"""CREATE TABLE satshole.operator_events (
        seq {db.serial_primary_key}, id TEXT NOT NULL UNIQUE, actor_id TEXT NOT NULL,
        kind TEXT NOT NULL,target_id TEXT NOT NULL,reason TEXT NOT NULL,
        payload TEXT NOT NULL,created_at BIGINT NOT NULL
    )""")
    await db.execute("""CREATE TABLE satshole.operator_applied (
        event_id TEXT PRIMARY KEY,applied_at BIGINT NOT NULL
    )""")
    await db.execute("""CREATE TABLE satshole.admin_refunds (
        submission_id TEXT PRIMARY KEY,competition_id TEXT NOT NULL,
        amount BIGINT NOT NULL,prize_debit BIGINT NOT NULL,
        operator_debit BIGINT NOT NULL,outgoing_id TEXT NOT NULL UNIQUE
    )""")


async def m009_review_indexes(db):
    if db.type == "SQLITE":
        await db.execute("""CREATE INDEX satshole.runs_replay_fingerprint
            ON runs (input_hash,seed)""")
    else:
        await db.execute("""CREATE INDEX runs_replay_fingerprint
            ON satshole.runs (input_hash,seed)""")
