import sqlite3

conn = sqlite3.connect(r'c:\Users\CHINTA KARUNAKAR\Desktop\RAG- StudyBot\backend\adaptive_study.db')
cursor = conn.cursor()

# 1. Count of chunks tagged as 'unknown'
cursor.execute("SELECT COUNT(*) FROM chunks WHERE concept = 'unknown'")
unknown_count = cursor.fetchone()[0]

# 2. Count of chunks tagged as 'General Concept'
cursor.execute("SELECT COUNT(*) FROM chunks WHERE concept = 'General Concept'")
general_count = cursor.fetchone()[0]

# 3. Percentage of total chunks using fallback concepts
cursor.execute('SELECT (COUNT(CASE WHEN concept IN ("unknown", "General Concept") THEN 1 END) * 100.0 / COUNT(*)) as fallback_percentage FROM chunks')
fallback_percentage = cursor.fetchone()[0]

# 4. Examples of correctly tagged chunks
cursor.execute('SELECT id, concept, parent_concept, difficulty, SUBSTR(text, 1, 100) as text_preview FROM chunks WHERE concept NOT IN ("unknown", "General Concept") LIMIT 5')
correct_chunks = cursor.fetchall()

# 5. Examples of poorly tagged chunks
cursor.execute('SELECT id, concept, parent_concept, difficulty, SUBSTR(text, 1, 100) as text_preview FROM chunks WHERE concept IN ("unknown", "General Concept") LIMIT 5')
poor_chunks = cursor.fetchall()

conn.close()

print(f'Unknown chunks: {unknown_count}, General Concept chunks: {general_count}, Fallback percentage: {fallback_percentage:.2f}%, Correct chunks: {correct_chunks}, Poor chunks: {poor_chunks}')
