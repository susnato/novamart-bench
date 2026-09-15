"""Download the NovaMart estate from Hugging Face into setup/data/.

Anonymous once the dataset is public; during the private phase set HF_TOKEN.
"""
import os, sys
from huggingface_hub import snapshot_download

REPO = "susnato/novamart-bench"

def main():
    dest = os.path.join(os.path.dirname(__file__), "..", "data")
    os.makedirs(dest, exist_ok=True)
    path = snapshot_download(REPO, repo_type="dataset", local_dir=dest)
    print(f"estate downloaded to {path}")

if __name__ == "__main__":
    sys.exit(main())
