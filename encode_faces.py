import os
import pickle
import face_recognition

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
KNOWN_DIR = os.path.join(BASE_DIR, "known_person")
ENCODE_FILE = os.path.join(BASE_DIR, "face_encodings.pkl")

if not os.path.exists(KNOWN_DIR):
    raise FileNotFoundError(f"known_person folder not found: {KNOWN_DIR}")

known_encodings = []
known_names = []

for person_name in os.listdir(KNOWN_DIR):
    person_path = os.path.join(KNOWN_DIR, person_name)

    if not os.path.isdir(person_path):
        continue

    for img_name in os.listdir(person_path):
        img_path = os.path.join(person_path, img_name)

        try:
            image = face_recognition.load_image_file(img_path)
            # num_jitters=5 → 5x more accurate encoding (slower but worth it)
            encodings = face_recognition.face_encodings(image, num_jitters=5)

            if encodings:
                known_encodings.append(encodings[0])
                known_names.append(person_name)
                print(f"  ✓ Encoded: {person_name} / {img_name}")
            else:
                print(f"  ✗ No face found in: {img_path}")

        except Exception as e:
            print(f"  ✗ Error processing {img_path}: {e}")

if known_encodings:
    with open(ENCODE_FILE, "wb") as f:
        pickle.dump((known_encodings, known_names), f)
    print(f"\n✓ Saved {len(known_encodings)} encodings for {len(set(known_names))} persons")
else:
    print("WARNING: No encodings saved.")
