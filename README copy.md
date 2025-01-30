# Presidio Image Redactor (presidio-image-redactor)

##  1. Overview

###  1.1. QuickLinks

- [Presidio Image Redactor (presidio-image-redactor)](#presidio-image-redactor-presidio-image-redactor)
  - [1. Overview](#1-overview)
    - [1.1. QuickLinks](#11-quicklinks)
    - [1.2. Summary](#12-summary)
    - [1.3. Cite](#13-cite)
    - [1.4. License](#14-license)
    - [1.5. Classification](#15-classification)
    - [1.6. Inputs](#16-inputs)
    - [1.7. ConfigSettings](#17-configsettings)
    - [1.8. Outputs](#18-outputs)
      - [1.8.1. Modes](#181-modes)
      - [1.8.2. Files](#182-files)
      - [1.8.3. Metadata](#183-metadata)
    - [1.9. Pre-requisites](#19-pre-requisites)
  - [2. Usage](#2-usage)
    - [2.1. Description](#21-description)
      - [2.1.1. FileSpecification](#211-filespecification)
        - [DICOM Images](#dicom-images)
    - [2.2. Workflow](#22-workflow)
    - [2.3. UseCases](#23-usecases)
      - [2.3.1. UseCase1](#231-usecase1)
      - [2.3.2. UseCase2](#232-usecase2)
      - [2.3.3. UseCase3](#233-usecase3)
    - [2.4. Logging](#24-logging)
  - [3. FAQ](#3-faq)
  - [4. Contributing](#4-contributing)

###  1.2. Summary
__Gear is under active development and current Release Candidate is subject to 
change. At present, running the Presidio-Image-Redactor as a Gear Rule is not 
supported, but will be added in a future release.__

__PLEASE NOTE:__ The methodologies used in this gear for identifying text & PHI
entities in medical images relies __heavily__ on statistics-based models and 
algorithms. These methodologies __are not__ fullproof and it is highly 
recommended that human-in-the-loop workflows are implemented to verify the 
identification of PHI or text entities. 

This gear builds upon Microsoft's open source Presidio SDK to scan DICOM images 
for potential Personal Identifiable Information (PII), report on PII findings, 
generate example images with bounding boxes embedded, generate ReaderTasks with
 annotated PHI entities, and the option to redact PII stored within 
DICOM pixel data.

###  1.3. Cite

Additional information on Microsoft's Presidio SDK can be found on their 
[website](https://microsoft.github.io/presidio/) and through 
their [GitHub Page](https://github.com/microsoft/presidio/). 

###  1.4. License

MIT

###  1.5. Classification

*Category:* Converter

*Gear Level:*

- [ ] Project
- [x] Subject
- [x] Session
- [x] Acquisition
- [ ] Analysis


###  1.6. Inputs

- DICOM image or series to be scanned/redacted
  - __Name__: image_file
  - __Type__: DICOM or archive (.zip)
  - __Optional__: false
  - __Classification__: DICOM
  - __Modalities__: US, CT, MR, XRay
  - __Description__: A single or multi-frame DICOM file. Isolated file or as 
  zipped DICOM series

- Coordinates of bounding boxes encapsulating PII
  - __Name__: bbox_coords
  - __Type__: source code (json)
  - __Optional__: true
  - __Classification__: source code
  - __Description__: Json containing the bounding box coordinates of a previous 
  scanning run.

###  1.7. ConfigSettings

- Debug
  - __Name__: debug
  - __Type__: boolean
  - __Description__: Log debug messages
  - __Default__: false

- Assignees
  - __Name__: Assignees
  - __type__: string
  - __Description__: Comma separated ist of Flywheel user emails to assign 
  ReaderTasks. If empty & Operating Mode=Detection+ReaderTasks, gear will fail.
  e.g. bob@flywheel.io, mary@flywheel.io
  - __Optional__: true

- Baseline Operating Mode 
  - __Name__: Baseline Operating Mode
  - __Type__: string
  - __Description__: Selects the operating mode for the gear. Detection only: 
  scans images for PHI & reports on findings. Detection+ReaderTasks: scans 
  images for PHI & creates ReaderTasks with found PHI. Dynamic PHI Redaction: 
  scans images for PHI & redacts them. RedactAllText: scans for all text within 
  images & redacts all of it.
  - __Default__: true

- Transformer Score Threshold
  - __Name__: Transformer Score Threshold
  - __Type__: integer
  - __Description__:The minimum confidence score (0 to 100) required for an 
  entity identified by the transformer to be considered PHI. Default=30
  - __Default__:30
  - __Minimum__: 0 
  - __Maximum__: 100

- Entity Frequency Threshold
  - __Name__: Entity Frequency Threshold
  - __Type__: integer
  - __Description__: Only applied on multi-frame files, frequency_threshold 
  specifies the minimum number of times (as a percentage 0 to 100) an entity 
  must appear across frames to be included in all frames. Default=30. Does not 
  impact single frame files.
  - __Default__:30
  - __Minimum__: 0 
  - __Maximum__: 100

- Use DICOM Metadata
  - __Name__: Use DICOM Metadata
  - __Type__: boolean
  - __Description__: If true, creates a regex recognizer from DICOM metadata to 
  facilitate identifying PHI text in DICOM pixel data. Default=False.
  - __Default__: false

- Entities to Find
  - __Name__: Entities to Find
  - __Type__: string
  - __Description__: List of entities the gear should look for. Current list  
  shows all possible entities; remove any entity not needed.
  - __Default__: PERSON,DATE_TIME,LOCATION,AGE,ID,PROFESSION,ORGANIZATION,
  PHONE_NUMBER,ZIP,USERNAME,EMAIL

  - API prefix Path
  - __Name__: apikey_path_prefix
  - __Type__: string
  - __Description__: Path for gear to find API credentials in docker environment. Provide when running gear as a gear rule to enable a Flywheel Bot to create reader tasks.
  - __Optional__: True 

  
###  1.8. Outputs

####  1.8.1. Modes
There are four operating modes for the image redactor gear. Regardless of 
selected operating mode, the `presidio-image-redactor` will tag files that it 
runs on with its gear name: `presidio-image-redactor` . 

1. Running the gear with __Detection Only__ will solely use the gear's scanning 
  capabilities. In this mode the gear will scan the image for PHI and generate 
  three review documents: 
> 1. A csv denoting PII entities found alongside corresponding bounding box 
coordinates 
> 2. A duplicate DICOM image with bounding boxes overlaid on the image
> 3. A `.json` file containing the coordinates for the bounding boxes 

>> Lastly, the gear will tag files and acquisition containers with `PHI-Found` 
if PII was identified and `PHI-Not-Found` if no PHI was identified.

2. Running the gear in __Detection+ReaderTasks__ mode will run the gear using 
the gear's scanning capabilities & produce the same three output as stated 
above. __Additionally__, the gear will create: 
> 1. A Reader Protocol, default name `presidio_default_protocol` for assigning 
ReaderTasks to 
> 2. A ReaderTask for the image that is being processed
> 3. Annotations of the returned bounding boxes, overlaying them on the 
ReaderTask image

>> Only 1 ReaderTask is created for a given `input_file` and is assigned using
the `Assignees` configuration option. 

3. __Dynamic PHI Redaction__ mode will utilize Optical Character Recognition 
(OCR) & Named Entity Recognition (NER) via the Transformer model 
__Deid-Roberta-i2b2__ to extract text from the input image, determine if it is
a PHI entity, and redact that area of the image. 

>> This operating mode permits an optional configuration option called 
"__Bbox_coords__". This _optional_ configuration option allows the user to 
input the bounding box coordinates from their _Detection Only_ job to the gear 
which will prevent the gear from scanning for a second time and proceed directly
to redacting the image. 

4. The final operating mode __RedactAllText__ uses the same OCR method as the 
method above, but __does not__ use NER or the Transformer.
>> Operating the gear in this mode will cause the gear to redact __any and all__
text that it finds in the image, __regardless if it is PHI or not__.

####  1.8.2. Files

- Identified PHI
  - __Name__: *PHI_INFO.presidio-image-redactor.<gear_version>*.csv
  - __Type__: csv
  - __Optional__: true
  - __Classification__: file
  - __Description__: A csv file containing located PII, which entity type, and 
  location in pixel data. Example documentation can be found in the 
  [Example Documents](
    ./docs/Example%20Documents/Example_PHI_Info.presidio-image-redactor.0.1.1.csv) 
  folder nested under the docs folder. 

- Bounding box DICOM(s)
  - __Name__: *bbox_<file-name>*.dcm or *bbox*.zip
  - __Type__: DICOM or archive (.zip)
  - __Optional__: true
  - __Classification__: file
  - __Description__: A single DICOM or DICOM series with burned in bounding 
  boxes surrounding identified PII.

- Redacted DICOM(s)
  - __Name__: *redacted_image-name_*.dcm or *redacted*.zip
  - __Type__: DICOM or archive (.zip)
  - __Optional__: true
  - __Classification__: file
  - __Description__: A single DICOM or DICOM series with burned in redaction 
  mask covering identified PII.

####  1.8.3. Metadata
- Gear Tag
  - __Name__: presidio-image-redactor
  - __Type__: tag
  - __Optional__: false
  - __Classification__: string
  - __Description__: A Flywheel tag added to input file to denote that this gear
  was run on it. 

- PHI Tag
  - __Name__: PHI-Found
  - __Type__: tag
  - __Optional__: false
  - __Classification__: string
  - __Description__: A Flywheel tag added to file containers indicating that 
  contain PII was found in the image. 

- No PHI Tag
  - __Name__: PHI-Not-Found
  - __Type__: tag
  - __Optional__: false
  - __Classification__: string
  - __Description__: A Flywheel tag added to the input file to denote that no 
  PHI was found by this gear. 

###  1.9. Pre-requisites

There are no specific pre-requisites in order to run this gear. All that is 
needed is a DICOM image or series. However, it is recommended that users have 
some pre-existing knowledge of de-identification processes to effectively 
identify which PII entities to look for and obscure. 

##  2. Usage

###  2.1. Description

This gear runs Optical Character Recognition (OCR), NER, and regex operations in
order to identify PII entities in DICOM pixel data. PII identified by these
algorithms are then cataloged for review by the user, consolidated into a
ReaderTask for human review, or redact to ensure subject privacy during
research. 

####  2.1.1. FileSpecification

##### DICOM Images

At this time, DICOM images or series must have the photometric interpretation
metadata value of MONOCHROME1, MONOCHROME2, or RGB. It is __highly__ recommended
to first run the __dicom-fixer__ on all DICOM files prior running
__Presidio Image Redactor__. Improper metadata formatting or alternative pixel
compression formats can impair or terminate the gear run.  

###  2.2. Workflow

A picture and description of the workflow

```mermaid
graph LR;
    A["Input<br>DICOM Image"]:::start;
    A --> X[Detection+ReaderTasks]:::input --> H;
    A --> Y[DetectionOnly]:::input --> D;
    A --> C[RedactAllText]:::input --> L; 
    
    H[Human-in-the-loop <br>ReaderTask annotations review]:::container-->I;
    D[Review any found PII <br> Decide if further scanning required]:::container-->E;
    L[Review images to determine if sufficient text removed]:::container --> K
    
    E((Run gear in <br> Dynamic PHI Redaction)):::gear --> F;
    I((Run<br>image-redaction-exporter)):::gear --> J;
    K[Review redacted outputs <br> Move redacted files to deid project]:::output
    
    
    F[Review redacted outputs <br> Move redacted files to deid project]:::output;
    J[Review redacted outputs <br> Move redacted files to deid project]:::output;

    classDef start fill:#415e9a,color:#fff
    classDef container fill:#415e9a,color:#fff
    classDef input fill:#008080,color:#fff
    classDef gear fill:#659,color:#fff
    classDef output fill:#005851
```

###  2.3. UseCases

####  2.3.1. UseCase1

*__PHI Detection + ReaderTask Pipeline__*:
You need to conduct PHI identification and redaction on your data set & require
human-in-the-loop verification of gear's identification performance. 
> 1. Prep the images by ensuring `dicom-fixer` has been run on all your images.
> 2. Enter the Flywheel emails of the individuals that will be reviewing the 
ReaderTasks. 
> 3. Select the `Detection+ReaderTasks` operating mode in the configuration 
options.
> 4. Run the gear & have your Readers complete their Assigned ReaderTasks.
Ensure Readers add or remove annotations on the image as needed. 
> 5. Once satisfied that your dataset has been de-identified, run the 
`image-redaction-exporter` to redact all areas indicated by ReaderTask 
annotations. 
> 6. Export data to clean project or instance, or simply begin data analytics. 

####  2.3.2. UseCase2
*__Simple PHI Scan & Redact__*
> 1. Prep the images by ensuring `dicom-fixer` has been run on all your images.
> 2. Select the `DetectionOnly` operating mode in the configuration 
options.
> 3. Run the gear & inspect output files showcasing identified PHI. 
> 4. Once satisfied that your dataset has been de-identified, run the gear again
and set the operating mode to `Dynamic PHI Redaction`. The gear will run and 
redact the entities that were found. You may choose to provide the bounding box
json as an additional input. 
> 5. Export data to clean project or instance, or simply begin data analytics. 

####  2.3.3. UseCase3
*__Complete Text Removal__*
> 1. Prep the images by ensuring `dicom-fixer` has been run on all your images.
> 3. Select the `RedactAllText` operating mode in the configuration 
options.
> 4. Run the gear & inspect output to determine if sufficient text has been 
removed from the images.  
> 5. Export data to clean project or instance, or simply begin data analytics. 

###  2.4. Logging

Logging implemented for this gear aims to provide the user with an understanding
of what flags were passed into the gear, what mode of operation the gear is
currently running, and what outputs are provided upon completion. 

To facilitate troubleshooting, raw OCR results can be created when running the
gear in debug mode. 

##  3. FAQ

[FAQ.md](FAQ.md)

##  4. Contributing

[For more information about how to get started contributing to that gear,
checkout [CONTRIBUTING.md](CONTRIBUTING.md).]
<!-- markdownlint-disable-file -->
