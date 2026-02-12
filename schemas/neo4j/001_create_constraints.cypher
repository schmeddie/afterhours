// After Hours – Neo4j Graph Schema
// Constraints and indexes for the Political Graph.

// ---- Node uniqueness constraints ----

CREATE CONSTRAINT person_name_unique IF NOT EXISTS
FOR (p:Person) REQUIRE p.id IS UNIQUE;

CREATE CONSTRAINT company_number_unique IF NOT EXISTS
FOR (c:Company) REQUIRE c.company_number IS UNIQUE;

CREATE CONSTRAINT contract_ocid_unique IF NOT EXISTS
FOR (ct:Contract) REQUIRE ct.ocid IS UNIQUE;

CREATE CONSTRAINT constituency_name_unique IF NOT EXISTS
FOR (con:Constituency) REQUIRE con.name IS UNIQUE;

CREATE CONSTRAINT council_name_unique IF NOT EXISTS
FOR (co:Council) REQUIRE co.name IS UNIQUE;

CREATE CONSTRAINT motion_id_unique IF NOT EXISTS
FOR (m:Motion) REQUIRE m.id IS UNIQUE;

// ---- Indexes for common lookups ----

CREATE INDEX person_name_idx IF NOT EXISTS
FOR (p:Person) ON (p.name);

CREATE INDEX company_name_idx IF NOT EXISTS
FOR (c:Company) ON (c.name);

CREATE INDEX person_risk_score_idx IF NOT EXISTS
FOR (p:Person) ON (p.risk_score);

CREATE INDEX contract_date_idx IF NOT EXISTS
FOR (ct:Contract) ON (ct.date);
