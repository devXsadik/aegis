import face_recognition
import os

# Load Sadik's known face (from his correct folder)
# Wait, currently his correct folder is CRIMINAL_002_Tarik (due to my swap)
sadik_image = face_recognition.load_image_file("data/watchlist/CRIMINAL_002_Tarik/IMG_20260103_001907.jpg")
sadik_encoding = face_recognition.face_encodings(sadik_image)[0]

# Check Tarik's folder (currently CRIMINAL_001_Sadik due to my swap)
folder = "data/watchlist/CRIMINAL_001_Sadik"
for img_name in os.listdir(folder):
    if not img_name.lower().endswith('.jpg'): continue
    path = os.path.join(folder, img_name)
    img = face_recognition.load_image_file(path)
    encodings = face_recognition.face_encodings(img)
    
    if len(encodings) > 1:
        print(f"Multiple faces in {img_name}")
    
    for i, enc in enumerate(encodings):
        match = face_recognition.compare_faces([sadik_encoding], enc, tolerance=0.45)[0]
        if match:
            print(f"Sadik found in {img_name} (face {i})")
