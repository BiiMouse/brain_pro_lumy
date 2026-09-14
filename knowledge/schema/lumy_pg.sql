-- Lumy 结构化型号库 DDL（PostgreSQL 13+）
-- 层级：pdf_sources → families / ppns / opns / naming_rules / regions
-- 家族与PPN/OPN 用名称关联（跨PDF查询友好），同PDF内唯一

CREATE TABLE IF NOT EXISTS pdf_sources (
    id           SERIAL PRIMARY KEY,
    file_name    VARCHAR(260) UNIQUE NOT NULL,
    pdf_path     VARCHAR(500),
    page_count   INT,
    parsed_at    TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS regions (
    id           SERIAL PRIMARY KEY,
    pdf_id       INT NOT NULL REFERENCES pdf_sources(id) ON DELETE CASCADE,
    page_start   INT NOT NULL,
    page_end     INT NOT NULL,
    region_type  VARCHAR(40) NOT NULL,
    title        VARCHAR(200),
    role         VARCHAR(20)
);

CREATE TABLE IF NOT EXISTS families (
    id           SERIAL PRIMARY KEY,
    pdf_id       INT NOT NULL REFERENCES pdf_sources(id) ON DELETE CASCADE,
    family_name  VARCHAR(120) NOT NULL,
    family_type  VARCHAR(20) DEFAULT 'normal',   -- normal|wildcard|commodity|degenerate
    notes        TEXT,
    evidence_page INT,
    UNIQUE (pdf_id, family_name)
);

CREATE TABLE IF NOT EXISTS ppns (
    id           SERIAL PRIMARY KEY,
    pdf_id       INT NOT NULL REFERENCES pdf_sources(id) ON DELETE CASCADE,
    family_name  VARCHAR(120),
    ppn          VARCHAR(150) NOT NULL,
    attributes   JSONB DEFAULT '{}',             -- 功能参数（来自Selector行/EC解码）
    evidence_page INT,
    evidence     TEXT,
    UNIQUE (pdf_id, ppn)
);

CREATE TABLE IF NOT EXISTS opns (
    id           SERIAL PRIMARY KEY,
    pdf_id       INT NOT NULL REFERENCES pdf_sources(id) ON DELETE CASCADE,
    family_name  VARCHAR(120),
    ppn          VARCHAR(150),                   -- 归属的PPN（可为空=未归属）
    opn          VARCHAR(160) NOT NULL,
    package      VARCHAR(200),
    packing      VARCHAR(200),
    notes        TEXT,
    evidence_page INT,
    UNIQUE (pdf_id, opn)
);

CREATE TABLE IF NOT EXISTS naming_rules (
    id           SERIAL PRIMARY KEY,
    pdf_id       INT NOT NULL REFERENCES pdf_sources(id) ON DELETE CASCADE,
    family_name  VARCHAR(120),
    pattern      VARCHAR(200),                   -- 如 LM317yyyz / MAX20029ATI_/V+
    positions    JSONB DEFAULT '[]',             -- [{segment, meaning, kind: functional|ordering}]
    source_page  INT,
    expanded     BOOLEAN DEFAULT FALSE           -- 纪律：只解码不展开
);

-- 查询索引
CREATE INDEX IF NOT EXISTS idx_families_name ON families (family_name);
CREATE INDEX IF NOT EXISTS idx_ppns_family   ON ppns (pdf_id, family_name);
CREATE INDEX IF NOT EXISTS idx_ppns_name     ON ppns (ppn);
CREATE INDEX IF NOT EXISTS idx_opns_name     ON opns (opn);
CREATE INDEX IF NOT EXISTS idx_opns_family   ON opns (pdf_id, family_name);
CREATE INDEX IF NOT EXISTS idx_regions_pdf   ON regions (pdf_id, region_type);
