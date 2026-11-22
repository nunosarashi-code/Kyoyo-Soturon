-- SQLite 3.37+。外部キーを有効にして接続する。
CREATE TABLE IF NOT EXISTS app_metadata (
    singleton INTEGER NOT NULL PRIMARY KEY CHECK (singleton = 1),
    dataset_kind TEXT NOT NULL CHECK (dataset_kind IN ('research', 'demo')),
    demo_loaded INTEGER NOT NULL DEFAULT 0 CHECK (demo_loaded IN (0, 1))
) STRICT;

CREATE TABLE IF NOT EXISTS sources (
    source_id TEXT NOT NULL PRIMARY KEY,
    author TEXT,
    year INTEGER CHECK (year BETWEEN 1 AND 9999),
    title TEXT,
    publication TEXT,
    doi_url TEXT,
    page TEXT,
    excerpt TEXT,
    extracted_on TEXT,
    verification_status TEXT NOT NULL
        CHECK (verification_status IN ('verified', 'unverified', 'unknown')),
    CHECK (verification_status <> 'verified' OR
        (title IS NOT NULL AND coalesce(author, publication, doi_url) IS NOT NULL)),
    UNIQUE (source_id, verification_status)
) STRICT;

CREATE TABLE IF NOT EXISTS species (
    species_id TEXT NOT NULL PRIMARY KEY,
    standard_name TEXT,
    scientific_name TEXT,
    genus TEXT,
    family TEXT,
    taxonomic_order TEXT,
    source_id TEXT REFERENCES sources(source_id),
    checked_on TEXT,
    name_status TEXT NOT NULL CHECK (name_status IN ('verified', 'unverified')),
    verified_source_status TEXT GENERATED ALWAYS AS (
        CASE WHEN name_status = 'verified' THEN 'verified' END
    ) VIRTUAL,
    CHECK (coalesce(standard_name, scientific_name) IS NOT NULL),
    CHECK (name_status <> 'verified' OR
        (standard_name IS NOT NULL AND scientific_name IS NOT NULL AND source_id IS NOT NULL)),
    FOREIGN KEY (source_id, verified_source_status)
        REFERENCES sources(source_id, verification_status)
) STRICT;

CREATE UNIQUE INDEX IF NOT EXISTS verified_scientific_name
    ON species (lower(scientific_name)) WHERE name_status = 'verified';

CREATE TABLE IF NOT EXISTS regions (
    region_id TEXT NOT NULL PRIMARY KEY,
    prefecture TEXT NOT NULL,
    locality TEXT NOT NULL,
    latitude REAL CHECK (latitude BETWEEN -90 AND 90),
    longitude REAL CHECK (longitude BETWEEN -180 AND 180),
    characteristics TEXT,
    survey_period TEXT,
    source_id TEXT REFERENCES sources(source_id)
) STRICT;

CREATE TABLE IF NOT EXISTS contexts (
    context_id TEXT NOT NULL PRIMARY KEY,
    region_id TEXT NOT NULL REFERENCES regions(region_id),
    context_label TEXT NOT NULL,
    period TEXT,
    user_group TEXT,
    survey_method TEXT,
    coverage TEXT,
    notes TEXT,
    source_id TEXT REFERENCES sources(source_id)
) STRICT;

CREATE TABLE IF NOT EXISTS folk_units (
    unit_id TEXT NOT NULL PRIMARY KEY,
    context_id TEXT NOT NULL REFERENCES contexts(context_id),
    unit_label TEXT,
    parent_unit_id TEXT,
    hierarchy_level TEXT,
    life_stage_size TEXT,
    criteria TEXT,
    unit_status TEXT NOT NULL CHECK (unit_status IN ('documented', 'provisional')),
    source_id TEXT REFERENCES sources(source_id),
    verified_source_status TEXT GENERATED ALWAYS AS (
        CASE WHEN unit_status = 'documented' THEN 'verified' END
    ) VIRTUAL,
    CHECK (parent_unit_id IS NULL OR parent_unit_id <> unit_id),
    CHECK (unit_status <> 'documented' OR source_id IS NOT NULL),
    UNIQUE (unit_id, context_id),
    FOREIGN KEY (parent_unit_id, context_id) REFERENCES folk_units(unit_id, context_id),
    FOREIGN KEY (source_id, verified_source_status)
        REFERENCES sources(source_id, verification_status)
) STRICT;

CREATE TRIGGER IF NOT EXISTS folk_unit_no_cycle_insert
AFTER INSERT ON folk_units WHEN NEW.parent_unit_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'hierarchy_cycle') WHERE EXISTS (
        WITH RECURSIVE ancestors(unit_id) AS (
            SELECT NEW.parent_unit_id
            UNION
            SELECT u.parent_unit_id FROM folk_units u JOIN ancestors a USING (unit_id)
            WHERE u.parent_unit_id IS NOT NULL
        )
        SELECT 1 FROM ancestors WHERE unit_id = NEW.unit_id
    );
END;

CREATE TRIGGER IF NOT EXISTS folk_unit_no_cycle_update
AFTER UPDATE OF parent_unit_id ON folk_units WHEN NEW.parent_unit_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'hierarchy_cycle') WHERE EXISTS (
        WITH RECURSIVE ancestors(unit_id) AS (
            SELECT NEW.parent_unit_id
            UNION
            SELECT u.parent_unit_id FROM folk_units u JOIN ancestors a USING (unit_id)
            WHERE u.parent_unit_id IS NOT NULL
        )
        SELECT 1 FROM ancestors WHERE unit_id = NEW.unit_id
    );
END;

CREATE TABLE IF NOT EXISTS local_names (
    local_name_id TEXT NOT NULL PRIMARY KEY,
    spelling TEXT NOT NULL,
    reading TEXT,
    context_id TEXT NOT NULL REFERENCES contexts(context_id),
    unit_id TEXT,
    form_type TEXT NOT NULL CHECK (form_type IN ('label', 'synonym', 'unresolved')),
    life_stage_size TEXT,
    notes TEXT,
    source_id TEXT REFERENCES sources(source_id),
    CHECK ((form_type = 'unresolved' AND unit_id IS NULL) OR
        (form_type <> 'unresolved' AND unit_id IS NOT NULL)),
    FOREIGN KEY (unit_id, context_id) REFERENCES folk_units(unit_id, context_id)
) STRICT;

CREATE UNIQUE INDEX IF NOT EXISTS same_local_name_attestation
    ON local_names (context_id, coalesce(unit_id, ''), spelling, coalesce(reading, ''),
                    coalesce(source_id, ''));

CREATE TABLE IF NOT EXISTS unit_species (
    mapping_id TEXT NOT NULL PRIMARY KEY,
    unit_id TEXT NOT NULL REFERENCES folk_units(unit_id),
    species_id TEXT NOT NULL REFERENCES species(species_id),
    certainty TEXT NOT NULL CHECK (certainty IN ('confirmed', 'probable', 'uncertain')),
    source_id TEXT REFERENCES sources(source_id),
    notes TEXT,
    verified_source_status TEXT GENERATED ALWAYS AS (
        CASE WHEN certainty = 'confirmed' THEN 'verified' END
    ) VIRTUAL,
    CHECK (certainty <> 'confirmed' OR source_id IS NOT NULL),
    FOREIGN KEY (source_id, verified_source_status)
        REFERENCES sources(source_id, verification_status)
) STRICT;

CREATE UNIQUE INDEX IF NOT EXISTS same_unit_species_attestation
    ON unit_species (unit_id, species_id, coalesce(source_id, ''));

CREATE TABLE IF NOT EXISTS name_species (
    name_mapping_id TEXT NOT NULL PRIMARY KEY,
    local_name_id TEXT NOT NULL REFERENCES local_names(local_name_id),
    species_id TEXT NOT NULL REFERENCES species(species_id),
    certainty TEXT NOT NULL CHECK (certainty IN ('confirmed', 'probable', 'uncertain')),
    source_id TEXT REFERENCES sources(source_id),
    notes TEXT,
    verified_source_status TEXT GENERATED ALWAYS AS (
        CASE WHEN certainty = 'confirmed' THEN 'verified' END
    ) VIRTUAL,
    CHECK (certainty <> 'confirmed' OR source_id IS NOT NULL),
    FOREIGN KEY (source_id, verified_source_status)
        REFERENCES sources(source_id, verification_status)
) STRICT;

CREATE UNIQUE INDEX IF NOT EXISTS same_name_species_attestation
    ON name_species (local_name_id, species_id, coalesce(source_id, ''));

CREATE TABLE IF NOT EXISTS uses (
    use_id TEXT NOT NULL PRIMARY KEY,
    context_id TEXT NOT NULL REFERENCES contexts(context_id),
    species_id TEXT REFERENCES species(species_id),
    unit_id TEXT,
    use_status TEXT NOT NULL CHECK (use_status IN ('used', 'not_used', 'unknown')),
    part TEXT,
    method TEXT,
    frequency TEXT,
    importance_notes TEXT,
    notes TEXT,
    source_id TEXT REFERENCES sources(source_id),
    CHECK ((species_id IS NULL) <> (unit_id IS NULL)),
    CHECK (use_status <> 'not_used' OR source_id IS NOT NULL),
    FOREIGN KEY (unit_id, context_id) REFERENCES folk_units(unit_id, context_id)
) STRICT;

CREATE TABLE IF NOT EXISTS use_purposes (
    use_id TEXT NOT NULL REFERENCES uses(use_id) ON DELETE CASCADE,
    purpose TEXT NOT NULL CHECK (
        purpose IN ('food', 'craft', 'tool', 'medicine', 'ritual', 'commercial', 'other')
    ),
    PRIMARY KEY (use_id, purpose)
) STRICT;

CREATE INDEX IF NOT EXISTS contexts_region ON contexts (region_id);
CREATE INDEX IF NOT EXISTS folk_units_context ON folk_units (context_id);
CREATE INDEX IF NOT EXISTS folk_units_parent ON folk_units (parent_unit_id, context_id);
CREATE INDEX IF NOT EXISTS local_names_unit ON local_names (unit_id, context_id);
CREATE INDEX IF NOT EXISTS unit_species_species ON unit_species (species_id);
CREATE INDEX IF NOT EXISTS name_species_species ON name_species (species_id);
CREATE INDEX IF NOT EXISTS uses_species_context ON uses (species_id, context_id);
CREATE INDEX IF NOT EXISTS uses_unit_context ON uses (unit_id, context_id);

-- 検索用の経路。直接記録された語の指示対象がある場合は、その記載を用いる。
-- NULL を含む経路は、対応が未登録の魚種・分類単位・地方名の検索を可能にする。
CREATE VIEW IF NOT EXISTS search_paths AS
    SELECT species_id, NULL AS context_id, NULL AS unit_id, NULL AS local_name_id FROM species
    UNION
    SELECT species_id, context_id, NULL, NULL FROM uses WHERE species_id IS NOT NULL
    UNION
    SELECT NULL, context_id, unit_id, NULL FROM folk_units
    UNION
    SELECT m.species_id, u.context_id, u.unit_id, NULL
        FROM unit_species m JOIN folk_units u USING (unit_id)
    UNION
    SELECT NULL, context_id, unit_id, local_name_id FROM local_names
    UNION
    SELECT m.species_id, n.context_id, n.unit_id, n.local_name_id
        FROM local_names n JOIN unit_species m USING (unit_id)
        WHERE NOT EXISTS (SELECT 1 FROM name_species s WHERE s.local_name_id = n.local_name_id)
    UNION
    SELECT m.species_id, n.context_id, n.unit_id, n.local_name_id
        FROM name_species m JOIN local_names n USING (local_name_id);
