import sys
sys.path.insert(0, 'backend')

from ingestion import extract_document_concepts, map_chunk_to_concept
import types
import json

# Sample document text about Autonomous Systems
sample_document = """
UNIT-I 
Introduction to Autonomous Systems
Definition of Autonomous Systems
Autonomous systems are systems or machines capable of performing tasks without human intervention by making decisions based on their programming and sensory inputs. These systems utilize technologies like artificial intelligence (AI), machine learning, and advanced control mechanisms to operate independently.

These systems can perceive their environment, process data, and make decisions or take actions based on that information. Autonomous systems have applications in various fields, such as robotics, vehicles, drones, and industrial automation.

For example:
Autonomous vehicles (like self-driving cars) use cameras, LIDAR, radar, and other sensors to navigate and make decisions about speed, direction, and route without human input.

LIDAR: Light Detection and Ranging is a remote sensing method used to examine the surface of the Earth.

Radar: The full form of RADAR is Radio Detection And Ranging. It is an electronic device that provides microwave segment or ultra-high frequency of the radio spectrum to identify obstacles to control the area of the spot or range of an object.

Characteristics of Autonomous Systems
1. Self-Sufficiency: Autonomous systems can perform their tasks without continuous human input.
2. Perception: They use sensors (e.g., cameras, LIDAR, radar) to understand their environment, identifying objects, obstacles, and changes around them.
3. Decision-Making: Autonomous systems process the sensory data, make decisions, and act based on algorithms, machine learning, or pre-programmed rules.
4. Adaptability: They can adjust their behaviour in response to dynamic environments, overcoming unforeseen obstacles or challenges.
"""

# Sample chunks from the document
sample_chunks = [
    "Autonomous systems are systems or machines capable of performing tasks without human intervention by making decisions based on their programming and sensory inputs.",
    "LIDAR: Light Detection and Ranging is a remote sensing method used to examine the surface of the Earth.",
    "Radar: The full form of RADAR is Radio Detection And Ranging. It is an electronic device that provides microwave segment.",
    "Characteristics of Autonomous Systems include Self-Sufficiency, Perception, Decision-Making, and Adaptability.",
    "Autonomous vehicles use cameras, LIDAR, radar, and other sensors to navigate and make decisions about speed, direction, and route without human input."
]

print("Testing new document-level concept extraction...")
print("=" * 80)

# Mock the Gemini response
mock_gemini_response = types.SimpleNamespace(
    text=json.dumps([
        {"concept": "Autonomous Systems", "parent_concept": "Robotics", "difficulty": "medium"},
        {"concept": "LIDAR", "parent_concept": "Sensors", "difficulty": "medium"},
        {"concept": "Radar", "parent_concept": "Sensors", "difficulty": "medium"},
        {"concept": "Decision Making", "parent_concept": "Autonomous Systems", "difficulty": "medium"},
        {"concept": "Computer Vision", "parent_concept": "Perception", "difficulty": "hard"}
    ])
)

# Mock database session with query method for usage tracking
mock_db = types.SimpleNamespace(
    query=lambda *args, **kwargs: types.SimpleNamespace(
        req_count=0,
        token_count=0
    )
)

# Mock the generate_content_with_limit function
import ingestion
original_generate = ingestion.generate_content_with_limit
ingestion.generate_content_with_limit = lambda *args, **kwargs: mock_gemini_response

# Test document-level concept extraction
print("\n1. Extracting document-level concepts...")
try:
    doc_concepts = extract_document_concepts(sample_document, "Autonomous Systems Test", mock_db)
    print(f"Extracted {len(doc_concepts)} document-level concepts:")
    for idx, concept in enumerate(doc_concepts, 1):
        print(f"  {idx}. {concept['concept']} (parent: {concept['parent_concept']}, difficulty: {concept['difficulty']})")
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
    doc_concepts = []

# Restore original function
ingestion.generate_content_with_limit = original_generate

# Test chunk-to-concept mapping
print("\n2. Mapping chunks to document concepts...")
tagged_count = 0
fallback_count = 0

for idx, chunk in enumerate(sample_chunks, 1):
    try:
        mapping = map_chunk_to_concept(chunk, doc_concepts)
        is_tagged = mapping.get("is_tagged", False)
        if is_tagged:
            tagged_count += 1
        else:
            fallback_count += 1
        
        print(f"  Chunk {idx}: {mapping['concept']} (parent: {mapping['parent_concept']}, tagged: {is_tagged})")
        print(f"    Text preview: {chunk[:80]}...")
    except Exception as e:
        print(f"  Chunk {idx}: Error - {e}")
        fallback_count += 1

# Calculate statistics
total_chunks = len(sample_chunks)
if total_chunks > 0:
    fallback_rate = (fallback_count / total_chunks) * 100
    tagged_rate = (tagged_count / total_chunks) * 100
    
    print("\n" + "=" * 80)
    print("RESULTS:")
    print(f"Total chunks: {total_chunks}")
    print(f"Successfully tagged: {tagged_count} ({tagged_rate:.1f}%)")
    print(f"Fallback: {fallback_count} ({fallback_rate:.1f}%)")
    print(f"Target fallback rate: <20%")
    print(f"Success: {'YES' if fallback_rate < 20 else 'NO'}")
    print("=" * 80)
