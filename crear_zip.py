import zipfile
import os

zip_name = "OBYRA.zip"
exclude_folders = {"__pycache__", ".git", "instance"}

with zipfile.ZipFile(zip_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
    for foldername, subfolders, filenames in os.walk("."):
        # Saltar carpetas que no queremos incluir
        if any(ex in foldername for ex in exclude_folders):
            continue
        for filename in filenames:
            if filename != zip_name:
                filepath = os.path.join(foldername, filename)
                zipf.write(filepath)

print(f"Archivo '{zip_name}' creado con éxito.")
