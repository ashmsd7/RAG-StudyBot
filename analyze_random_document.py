import sys
sys.path.insert(0, 'backend')

import random
import sqlite3

def analyze_random_document():
    # Connect directly to database to avoid ORM schema mismatch
    conn = sqlite3.connect('adaptive_study.db')
    cursor = conn.cursor()
    
    try:
        # Get all documents
        cursor.execute("SELECT id, user_id, title, upload_date FROM documents")
        documents = cursor.fetchall()
        
        if not documents:
            print("No documents found in database.")
            return
        
        print(f"Found {len(documents)} documents in database:")
        for doc in documents:
            print(f"  - {doc[0]}: {doc[2]} (user: {doc[1]})")
        
        # Pick a random document
        selected_doc = random.choice(documents)
        doc_id, user_id, title, upload_date = selected_doc
        print(f"\nSelected document: {title} (ID: {doc_id})")
        
        # Get existing chunks for this document
        cursor.execute("""
            SELECT id, document_id, text, concept, parent_concept, difficulty, is_tagged, page_number, document_title
            FROM chunks
            WHERE document_id = ?
        """, (doc_id,))
        chunks = cursor.fetchall()
        
        if not chunks:
            print(f"No chunks found for document {doc_id}")
            return
        
        print(f"Found {len(chunks)} existing chunks in database")
        
        # Convert chunks to dict format for analysis
        processed_chunks = []
        for chunk in chunks:
            processed_chunks.append({
                'chunk_id': chunk[0],
                'text': chunk[2],
                'concept': chunk[3],
                'parent_concept': chunk[4],
                'difficulty': chunk[5],
                'is_tagged': chunk[6],
                'page_number': chunk[7],
                'document_title': chunk[8]
            })
        
        # Calculate metrics
        total_chunks = len(processed_chunks)
        tagged_chunks = sum(1 for chunk in processed_chunks if chunk.get('is_tagged', False))
        fallback_chunks = total_chunks - tagged_chunks
        fallback_percentage = (fallback_chunks / total_chunks * 100) if total_chunks > 0 else 0
        
        # Extract unique concepts and parent-child relationships
        concepts = {}
        parent_child_pairs = set()
        
        for chunk in processed_chunks:
            concept = chunk['concept']
            parent = chunk['parent_concept']
            
            if concept not in concepts:
                concepts[concept] = {
                    'count': 0,
                    'parent': parent,
                    'difficulty': chunk['difficulty'],
                    'is_tagged': chunk.get('is_tagged', False)
                }
            concepts[concept]['count'] += 1
            
            if parent and parent != concept:
                parent_child_pairs.add((parent, concept))
        
        total_concepts = len(concepts)
        total_parent_child = len(parent_child_pairs)
        
        # Get top 20 concepts by frequency
        top_concepts = sorted(concepts.items(), key=lambda x: x[1]['count'], reverse=True)[:20]
        
        # Build concept hierarchies
        hierarchies = {}
        for parent, child in parent_child_pairs:
            if parent not in hierarchies:
                hierarchies[parent] = []
            hierarchies[parent].append(child)
        
        # Print results
        print("\n" + "=" * 80)
        print("ANALYSIS RESULTS")
        print("=" * 80)
        
        print(f"\n1. Total chunks: {total_chunks}")
        print(f"2. Total concepts extracted: {total_concepts}")
        print(f"3. Total parent-child relationships: {total_parent_child}")
        print(f"4. Fallback percentage: {fallback_percentage:.1f}% ({fallback_chunks}/{total_chunks} chunks)")
        
        print(f"\n5. Top 20 concepts:")
        for idx, (concept, data) in enumerate(top_concepts, 1):
            tagged_status = "TAGGED" if data['is_tagged'] else "FALLBACK"
            print(f"   {idx}. {concept} (parent: {data['parent']}, difficulty: {data['difficulty']}, "
                  f"count: {data['count']}, {tagged_status})")
        
        print(f"\n6. Concept hierarchies:")
        for parent, children in sorted(hierarchies.items()):
            print(f"   {parent}")
            for child in sorted(children):
                child_data = concepts.get(child, {})
                tagged_status = "TAGGED" if child_data.get('is_tagged', False) else "FALLBACK"
                print(f"      └── {child} (difficulty: {child_data.get('difficulty', 'unknown')}, "
                      f"chunks: {child_data.get('count', 0)}, {tagged_status})")
        
        print("\n" + "=" * 80)
        
    finally:
        conn.close()

if __name__ == "__main__":
    analyze_random_document()
