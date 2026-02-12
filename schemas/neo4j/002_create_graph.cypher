// After Hours – Neo4j Graph Seed Template
// Example nodes and relationships illustrating the target schema.
// In production these are created by the graph sync pipeline, not this script.

// ---- Example Person node ----
// MERGE (p:Person {
//   id: 'parliament-1234',
//   name: 'Jane Smith',
//   status: 'pending_review',
//   risk_score: 0,
//   house: 'Commons',
//   party: 'Labour',
//   date_of_birth: date('1970-05-15')
// })

// ---- Relationship types reference ----
//
//  (:Person)-[:MP_FOR {start_date, end_date}]->(:Constituency)
//  (:Person)-[:MEMBER_OF {start_date, end_date}]->(:Committee)
//  (:Person)-[:DIRECTOR_OF {start_date, end_date, role}]->(:Company)
//  (:Person)-[:HAS_INTEREST {category, description, date_registered}]->(:Company)
//  (:Company)-[:AWARDED_CONTRACT {award_date}]->(:Contract)
//  (:Person)-[:VOTED_ON {direction}]->(:Motion)
//  (:Motion)-[:HEARD_BY]->(:Council)
//  (:Person)-[:COUNCILLOR_AT]->(:Council)

// ---- No-op statement so this file parses cleanly ----
RETURN 1;
