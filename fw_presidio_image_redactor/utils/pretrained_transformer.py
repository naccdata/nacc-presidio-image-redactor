"""Load a pretrained transformer model from the HuggingFace Hub."""

from huggingface_hub import snapshot_download
from transformers import AutoModelForTokenClassification, AutoTokenizer


def get_pretrained_transformer_model(model_path: str = "obi/deid_roberta_i2b2") -> None:
    """Download a pretrained transformer model from the HuggingFace Hub.

    Args:
        model_path (str): Path for model on HuggingFace

    Returns:
        None
    """
    # Get snapshot from HuggingFace Hub
    transformers_model = model_path
    snapshot_download(repo_id=transformers_model)

    # Instantiate to make sure it's downloaded during installation and not runtime
    AutoTokenizer.from_pretrained(transformers_model)
    AutoModelForTokenClassification.from_pretrained(transformers_model)


if __name__ == "__main__":
    get_pretrained_transformer_model()
