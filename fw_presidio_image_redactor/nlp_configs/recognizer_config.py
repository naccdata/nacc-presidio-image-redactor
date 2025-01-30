"""File containing the default parameters for transformer model.

Default parameters additionally assist in mapping of transformer output labels to
presidio entities

"""

BERT_DEID_CONFIGURATION = {
    "DEFAULT_MODEL_PATH": ".cache/huggingface/hub/models/obi_deid_roberta_i2b2",  # obi/deid_roberta_i2b2
    "LABELS_TO_IGNORE": ["O"],
    "DEFAULT_EXPLANATION": "Identified as {} by the obi/deid_roberta_i2b2 NER model",
    "SUB_WORD_AGGREGATION": "simple",
    "DATASET_TO_PRESIDIO_MAPPING": {
        "DATE": "DATE_TIME",
        "DOCTOR": "PERSON",
        "PATIENT": "PERSON",
        "HOSPITAL": "ORGANIZATION",
        "MEDICALRECORD": "ID",
        "IDNUM": "ID",
        "ORGANIZATION": "ORGANIZATION",
        "ZIP": "ID",
        "PHONE": "PHONE_NUMBER",
        "USERNAME": "PERSON",
        "STREET": "LOCATION",
        "PROFESSION": "PROFESSION",
        "COUNTRY": "LOCATION",
        "LOCATION-OTHER": "LOCATION",
        "FAX": "PHONE_NUMBER",
        "EMAIL": "EMAIL",
        "STATE": "LOCATION",
        "DEVICE": "ORGANIZATION",
        "ORG": "ORGANIZATION",
        "AGE": "AGE",
    },
    "MODEL_TO_PRESIDIO_MAPPING": {
        "PER": "PERSON",
        "PERSON": "PERSON",
        "LOC": "LOCATION",
        "LOCATION": "LOCATION",
        "GPE": "LOCATION",
        "ORG": "ORGANIZATION",
        "ORGANIZATION": "ORGANIZATION",
        "NORP": "NRP",
        "AGE": "AGE",
        "ID": "ID",
        "EMAIL": "EMAIL",
        "PATIENT": "PERSON",
        "STAFF": "PERSON",
        "HOSP": "ORGANIZATION",
        "PATORG": "ORGANIZATION",
        "DATE": "DATE_TIME",
        "TIME": "DATE_TIME",
        "PHONE": "PHONE_NUMBER",
        "HCW": "PERSON",
        "HOSPITAL": "ORGANIZATION",
        "FACILITY": "LOCATION",
    },
    "CHUNK_OVERLAP_SIZE": 8,
    "CHUNK_SIZE": 25,
    # "ID_SCORE_MULTIPLIER": 0.4,
    # "ID_ENTITY_NAME": "ID",
}
