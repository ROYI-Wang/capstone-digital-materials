// Neo4j Import Guide - 瞿秋白
// 1. Put nodes.csv and relationships.csv in Neo4j import directory
// 2. Run:

LOAD CSV WITH HEADERS FROM 'file:///nodes.csv' AS row
MERGE (n:KGNode {id: row.node_id})
SET n.labels = row.labels, n.name = row.name, n.node_type = row.node_type,
    n.article_id = row.article_id, n.segment_id = row.segment_id,
    n.title = row.title, n.text = row.text;

LOAD CSV WITH HEADERS FROM 'file:///relationships.csv' AS row
MATCH (s:KGNode {id: row.source_id})
MATCH (t:KGNode {id: row.target_id})
MERGE (s)-[r:KG_RELATION {type: row.type}]->(t)
SET r.relation = row.relation, r.polarity = row.polarity,
    r.stance_score = toFloat(row.stance_score), r.intensity = toFloat(row.intensity),
    r.relation_subtype = row.relation_subtype,
    r.evidence = row.evidence, r.confidence = row.confidence,
    r.article_id = row.article_id, r.segment_id = row.segment_id;