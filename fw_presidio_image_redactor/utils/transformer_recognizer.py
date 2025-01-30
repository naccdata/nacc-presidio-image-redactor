"""Module used to load the transformers model & tokenizer for Presidio Recognizer."""

import copy
import logging
from typing import List, Optional, Tuple

import torch
from presidio_analyzer import (
    AnalysisExplanation,
    EntityRecognizer,
    RecognizerResult,
)
from presidio_analyzer.nlp_engine import NlpArtifacts

from fw_presidio_image_redactor.nlp_configs.recognizer_config import (
    BERT_DEID_CONFIGURATION,
)

logger = logging.getLogger("presidio-analyzer")

try:
    from transformers import (
        AutoModelForTokenClassification,
        AutoTokenizer,
        TokenClassificationPipeline,
        pipeline,
    )

except ImportError:
    logger.error("transformers is not installed")


# Presidio reference material for transformer recognizer
# https://github.com/microsoft/presidio/blob/main/docs/analyzer/nlp_engines/transformers.md
class TransformersRecognizer(EntityRecognizer):
    """Wrapper for a transformers model, if needed to be used within Presidio Analyzer.

    The class loads models hosted on HuggingFace - https://huggingface.co/
    and loads the model and tokenizer into a TokenClassification pipeline.
    Samples are split into short text chunks, ideally shorter than max_length
    input_ids of the individual model, to avoid truncation by the Tokenizer and loss of
    information

    Example:
        ``
        from presidio_analyzer import AnalyzerEngine, RecognizerRegistry
        from local import transformer_config

        transformers_recognizer = TransformersRecognizer(
            model_path=transformer_config.get("model_path"),
            supported_entities = transformer_config.get("supported_entities")
        )
        transformers_recognizer.load_transformer(**transformer_config)

        registry = RecognizerRegistry()
        registry.add_recognizer(transformers_recognizer)
        analyzer = AnalyzerEngine(registry=registry)

        sample = "My name is Christopher and I live in Irbid."
        results = analyzer.analyze(sample, language="en",return_decision_process=True)
        for result in results:
            print(result,'----', sample[result.start:result.end])
        ``

    Returns:
            List[RecognizerResult]: List of found entities as RecResult objects

    """

    def __init__(
        self,
        model_path: Optional[str] = None,
        pipeline: Optional[TokenClassificationPipeline] = None,
        supported_entities: Optional[List[str]] = None,
    ):
        """Initializes the TransformersRecognizer class.

        Args:
            model_path (Optional[str], optional): Path to model. Defaults to None.
            pipeline (Optional[TokenClassificationPipeline], optional): Designated Pipeline. Defaults to None.
            supported_entities (Optional[List[str]], optional): supported entities. Defaults to None.

        """
        if not supported_entities:
            supported_entities = BERT_DEID_CONFIGURATION["PRESIDIO_SUPPORTED_ENTITIES"]
        super().__init__(
            supported_entities=supported_entities,
            name=f"Transformers model {model_path}",
        )

        self.model_path = model_path
        self.pipeline = pipeline
        self.is_loaded = False

        self.aggregation_mechanism = None
        self.ignore_labels = None
        self.model_to_presidio_mapping = None
        self.entity_mapping = None
        self.default_explanation = None
        self.text_overlap_length = None
        self.chunk_length = None
        self.id_entity_name = None
        self.id_score_reduction = None

    def load_transformer(self, **kwargs) -> None:
        """Load external configuration parameters and set default values.

        Args:
            kwargs (dict): Following arguments drawn from model config file.
                DATASET_TO_PRESIDIO_MAPPING [dict]: maps dataset format to Presidio
                format
                MODEL_TO_PRESIDIO_MAPPING [dict]: maps model labels to Presidio entities
                SUB_WORD_AGGREGATION [str]: define how to aggregate sub-word tokens into
                full words and spans as defined in HuggingFace
                https://huggingface.co/transformers/v4.8.0/main_classes/pipelines.html#transformers.TokenClassificationPipeline # noqa E501
                CHUNK_OVERLAP_SIZE [int]: number of overlapping characters in each chunk
                CHUNK_SIZE [int]: number of characters in each chunk of text
                LABELS_TO_IGNORE [List[str]]: List of entities to ignore.
                Defaults to ["O"]
                DEFAULT_EXPLANATION [str]: string format to use for prediction
                explanations
                ID_ENTITY_NAME [str]: name of the ID entity
                ID_SCORE_REDUCTION [float]: score multiplier for ID entities

        Returns:
            None

        """
        self.entity_mapping = kwargs.get("DATASET_TO_PRESIDIO_MAPPING", {})
        self.model_to_presidio_mapping = kwargs.get("MODEL_TO_PRESIDIO_MAPPING", {})
        self.ignore_labels = kwargs.get("LABELS_TO_IGNORE", ["O"])
        self.aggregation_mechanism = kwargs.get("SUB_WORD_AGGREGATION", "simple")
        self.default_explanation = kwargs.get(
            "DEFAULT_EXPLANATION",
            "Identified as {} by the obi/deid_roberta_i2b2 NER model",
        )
        self.text_overlap_length = kwargs.get("CHUNK_OVERLAP_SIZE", 40)
        self.chunk_length = kwargs.get("CHUNK_SIZE", 600)
        self.id_entity_name = kwargs.get("ID_ENTITY_NAME", "ID")
        self.id_score_reduction = kwargs.get("ID_SCORE_REDUCTION", 1)

        if not self.pipeline:
            if not self.model_path:
                self.model_path = "obi/deid_roberta_i2b2"
                logger.warning(
                    "Both 'model' and 'model_path' arguments are None. Using default model_path=%s",
                    self.model_path,
                )

        self._load_pipeline()

    def _load_pipeline(self) -> None:
        """Initialize NER transformers pipeline using the model_path provided."""
        logger.debug("Initializing NER pipeline using %s path", self.model_path)
        device = 0 if torch.cuda.is_available() else -1
        self.pipeline = pipeline(
            "ner",
            model=AutoModelForTokenClassification.from_pretrained(self.model_path),
            tokenizer=AutoTokenizer.from_pretrained(self.model_path),
            # Will attempt to group sub-entities to word level
            aggregation_strategy=self.aggregation_mechanism,
            device=device,
            framework="pt",
            ignore_labels=self.ignore_labels,
        )

        self.is_loaded = True

    def get_supported_entities(self) -> List[str]:
        """Return supported entities by this model.

        Returns:
            List[str]: List of supported entities

        """
        return self.supported_entities

    # Method to use transformers with Presidio as an external recognizer.
    def analyze(
        self, text: str, entities: List[str], nlp_artifacts: NlpArtifacts
    ) -> List[RecognizerResult]:
        """Analyze text using transformers model to produce NER tagging.

        Args:
            text (str): The text for analysis
            entities (List[str]): List of entities to analyze, kept for absClass
            compliance
            nlp_artifacts (NlpArtifacts): NLP artifacts, kept for absClass compliance

        Return:
            results (List[RecognizerResult]): List of identified entities

        """
        results = list()
        # Run transformer model on the provided text
        ner_results = self._get_ner_results_for_text(text)

        for res in ner_results:
            res["entity_group"] = self.__check_label_transformer(res["entity_group"])
            if not res["entity_group"]:
                continue

            if res["entity_group"] == self.id_entity_name:
                logger.info(
                    "ID entity found, multiplying score by %s", self.id_score_reduction
                )
                res["score"] = res["score"] * self.id_score_reduction

            textual_explanation = self.default_explanation.format(res["entity_group"])
            explanation = self.build_transformers_explanation(
                float(round(res["score"], 2)), textual_explanation, res["word"]
            )
            transformers_result = self._convert_to_recognizer_result(res, explanation)

            results.append(transformers_result)

        return results

    @staticmethod
    def split_text_to_word_chunks(
        input_length: int, chunk_length: int, overlap_length: int
    ) -> List[Tuple[int, int]]:
        """Calculates chunk length with appropriate overlap length.

        Args:
            input_length (int): Length of the input sequence
            chunk_length (int): Designated length of chunks
            overlap_length (int): Amount of overlap between chunks

        Returns:
            List[Tuple[int]]: List of chunks

        """
        if input_length < chunk_length:
            return [[0, input_length]]
        if chunk_length <= overlap_length:
            logger.warning(
                "overlap_length should be shorter than chunk_length, setting "
                "overlap_length to half of chunk_length"
            )
            overlap_length = chunk_length // 2
        return [
            (i, min([i + chunk_length, input_length]))
            for i in range(
                0, input_length - overlap_length, chunk_length - overlap_length
            )
        ]

    def _get_ner_results_for_text(self, text: str) -> List[dict]:
        """The function runs model inference on the provided text.

        The text is split into chunks with n overlapping characters.
        The results are then aggregated and duplications are removed.

        Args:
            text (str): The text to run inference on

        Returns:
            predictions (List[dict]): List of entity predictions on the word level

        """
        model_max_length = self.pipeline.tokenizer.model_max_length
        # calculate inputs based on the text
        text_length = len(text)
        # split text into chunks
        if text_length <= model_max_length:
            predictions = self.pipeline(text)
        else:
            logger.info(
                "splitting the text into chunks, length %s > %s",
                text_length,
                model_max_length,
            )
            predictions = list()
            chunk_indexes = self.split_text_to_word_chunks(
                text_length, self.chunk_length, self.text_overlap_length
            )

            # iterate over text chunks and run inference
            for chunk_start, chunk_end in chunk_indexes:
                chunk_text = text[chunk_start:chunk_end]
                chunk_preds = self.pipeline(chunk_text)

                # align indexes to match the original text - add to each position the value of chunk_start
                aligned_predictions = list()
                for prediction in chunk_preds:
                    prediction_tmp = copy.deepcopy(prediction)
                    prediction_tmp["start"] += chunk_start
                    prediction_tmp["end"] += chunk_start
                    aligned_predictions.append(prediction_tmp)

                predictions.extend(aligned_predictions)

        # remove duplicates
        predictions = [dict(t) for t in {tuple(d.items()) for d in predictions}]
        return predictions

    @staticmethod
    def _convert_to_recognizer_result(
        prediction_result: dict, explanation: AnalysisExplanation
    ) -> RecognizerResult:
        """Parses NER model predictions into a RecognizerResult format.

        Args:
            prediction_result (dict): A single example of entity prediction
            explanation (AnalysisExplanation): Textual representation of prediction

        Returns:
            RecognizerResult: RecognizerResult used for model evaluation calculations

        """
        transformers_results = RecognizerResult(
            entity_type=prediction_result["entity_group"],
            start=prediction_result["start"],
            end=prediction_result["end"],
            score=float(round(prediction_result["score"], 2)),
            analysis_explanation=explanation,
        )

        return transformers_results

    def build_transformers_explanation(
        self,
        original_score: float,
        explanation: str,
        pattern: str,
    ) -> AnalysisExplanation:
        """Create explanation for why this result was detected.

        Args:
            original_score (float): Score given by this recognizer
            explanation (str): Explanation string
            pattern (str): Regex pattern used

        Returns:
            AnalysisExplanation: Structured explanation with scores for NER predictions

        """
        explanation = AnalysisExplanation(
            recognizer=self.__class__.__name__,
            original_score=float(original_score),
            textual_explanation=explanation,
            pattern=pattern,
        )
        return explanation

    def __check_label_transformer(self, label: str) -> Optional[str]:
        """Validates predicted label and maps string to Presidio representation.

        Args:
            label (str): Predicted label by the model

        Returns:
            Optional[str[]]: the adjusted entity name

        """
        # convert model label to presidio label
        entity = self.model_to_presidio_mapping.get(label, None)

        if entity in self.ignore_labels:
            return None

        if entity is None:
            logger.warning("Found unrecognized label %s, returning entity as is", label)
            return label

        if entity not in self.supported_entities:
            logger.warning("Found entity %s which is not supported by Presidio", entity)
            return entity
        return entity
