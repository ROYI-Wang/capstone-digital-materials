// Neo4j 导入示例
LOAD CSV WITH HEADERS FROM 'file:///nodes.csv' AS row
MERGE (n:KGNode {id: row.node_id})
SET n.labels = row.labels, n.name = row.name, n.node_type = row.node_type,
    n.article_id = row.article_id, n.segment_id = row.segment_id, n.title = row.title, n.text = row.text;

LOAD CSV WITH HEADERS FROM 'file:///relationships.csv' AS row
MATCH (s:KGNode {id: row.source_id})
MATCH (t:KGNode {id: row.target_id})
MERGE (s)-[r:KG_RELATION {type: row.type, relation: row.relation, segment_id: row.segment_id, evidence: row.evidence}]->(t)
SET r.polarity = row.polarity, r.confidence = row.confidence, r.article_id = row.article_id;