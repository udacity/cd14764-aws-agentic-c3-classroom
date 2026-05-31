"""
seed_documents.py
=================
Uploads CS and Biology paper documents to the demo S3 bucket.

Run this ONCE after deploying the demo CloudFormation stack
(lesson-08-demo-rag) and BEFORE creating the Knowledge Bases in the
Bedrock console.

Usage:
    python seed_documents.py

The bucket name is read from the CloudFormation stack output automatically.
Requires AWS credentials with S3 write access.
"""

import boto3
import os
import sys
from dotenv import load_dotenv

load_dotenv()
AWS_REGION = os.environ.get("AWS_REGION", "us-west-2")

CS_PAPERS = [
    {
        "doc_id": "CS-001", "title": "Deep Learning for Genomic Sequence Analysis",
        "source": "Journal of ML Research, 2024",
        "content": (
            "We present a transformer-based architecture for predicting gene expression "
            "levels from DNA sequences. Our model achieves 94% accuracy on the benchmark "
            "GenomeBERT dataset, outperforming previous CNN-based approaches by 12%. "
            "The attention mechanism reveals biologically meaningful motifs."
        ),
        "keywords": ["machine learning", "deep learning", "genomics", "transformer", "gene expression", "DNA"],
    },
    {
        "doc_id": "CS-002", "title": "Federated Learning in Healthcare: Privacy-Preserving ML",
        "source": "IEEE Transactions on AI, 2024",
        "content": (
            "Federated learning enables hospitals to collaboratively train ML models "
            "without sharing patient data. We demonstrate a federated approach for "
            "predicting drug interactions that achieves 91% accuracy while maintaining "
            "HIPAA compliance. Communication overhead is reduced 60% via gradient compression."
        ),
        "keywords": ["federated learning", "healthcare", "privacy", "drug interactions", "machine learning"],
    },
    {
        "doc_id": "CS-003", "title": "Reinforcement Learning for Protein Folding Optimization",
        "source": "NeurIPS 2024 Proceedings",
        "content": (
            "We apply deep reinforcement learning to optimize protein folding simulations. "
            "Our RL agent explores conformational space 50x faster than molecular dynamics. "
            "The approach discovers novel folding pathways for 3 previously unsolved proteins, "
            "validated against experimental X-ray crystallography data."
        ),
        "keywords": ["reinforcement learning", "protein folding", "optimization", "molecular dynamics"],
    },
    {
        "doc_id": "CS-004", "title": "Natural Language Processing for Biomedical Literature Mining",
        "source": "ACL 2024 Proceedings",
        "content": (
            "Our NLP pipeline extracts gene-disease associations from 2 million PubMed "
            "abstracts with 89% F1 score. We fine-tune BioBERT on a curated dataset of "
            "10,000 annotated abstracts. The system identifies 340 novel gene-disease "
            "associations not present in existing databases."
        ),
        "keywords": ["NLP", "biomedical", "text mining", "gene-disease", "BioBERT", "machine learning"],
    },
    {
        "doc_id": "CS-005", "title": "Graph Neural Networks for Drug Discovery",
        "source": "ICML 2024 Workshop",
        "content": (
            "We introduce MolGNN, a graph neural network for predicting molecular "
            "properties relevant to drug discovery. MolGNN achieves state-of-the-art "
            "results on 8 of 12 MoleculeNet benchmarks. The model identifies 15 "
            "candidate compounds for malaria treatment, 3 of which show promise in vitro."
        ),
        "keywords": ["graph neural networks", "drug discovery", "molecular properties", "machine learning"],
    },
    {
        "doc_id": "CS-006", "title": "Quantum Computing Algorithms for Cryptography",
        "source": "ACM Computing Surveys, 2024",
        "content": (
            "We survey post-quantum cryptographic algorithms resistant to Shor's algorithm. "
            "Lattice-based schemes show the best balance of security and performance. "
            "We benchmark 5 NIST finalist algorithms on current quantum simulators."
        ),
        "keywords": ["quantum computing", "cryptography", "post-quantum", "lattice"],
    },
]

BIO_PAPERS = [
    {
        "doc_id": "BIO-001", "title": "CRISPR-Cas9 Applications in Crop Genomics",
        "source": "Nature Biotechnology, 2024",
        "content": (
            "We demonstrate CRISPR-Cas9 gene editing for drought resistance in wheat. "
            "Targeted knockout of the TaDREB2 gene increases water-use efficiency by 40%. "
            "Field trials across 3 climate zones confirm yield improvements of 15-25% "
            "under water-stressed conditions."
        ),
        "keywords": ["CRISPR", "genomics", "crop science", "gene editing", "drought resistance"],
    },
    {
        "doc_id": "BIO-002", "title": "Machine Learning Identifies Novel Cancer Biomarkers",
        "source": "Cancer Research, 2024",
        "content": (
            "Using ML-based analysis of single-cell RNA sequencing data, we identify "
            "7 novel biomarkers for early-stage pancreatic cancer. A random forest classifier "
            "achieves 96% sensitivity and 88% specificity. Three biomarkers show promise "
            "for liquid biopsy detection, enabling non-invasive screening."
        ),
        "keywords": ["machine learning", "cancer", "biomarkers", "RNA sequencing", "genomics"],
    },
    {
        "doc_id": "BIO-003", "title": "Microbiome-Host Interactions in Inflammatory Disease",
        "source": "Cell, 2024",
        "content": (
            "We map the gut microbiome's influence on inflammatory bowel disease using "
            "metagenomic sequencing of 500 patients. Specific Bacteroides species correlate "
            "with disease remission (p<0.001). Fecal transplant from remission patients "
            "reduces inflammation markers by 65% in mouse models."
        ),
        "keywords": ["microbiome", "inflammatory disease", "metagenomics", "gut health"],
    },
    {
        "doc_id": "BIO-004", "title": "Genomic Analysis of Antibiotic Resistance Evolution",
        "source": "Science, 2024",
        "content": (
            "Whole-genome sequencing of 1,200 MRSA isolates reveals 4 novel resistance "
            "mechanisms involving horizontal gene transfer. We trace resistance gene "
            "flow across hospital networks using phylogenetic analysis. ML-based prediction "
            "of resistance patterns achieves 93% accuracy."
        ),
        "keywords": ["genomics", "antibiotic resistance", "MRSA", "gene transfer", "machine learning"],
    },
    {
        "doc_id": "BIO-005", "title": "Protein Engineering for Enzyme Optimization",
        "source": "Nature Chemical Biology, 2024",
        "content": (
            "Directed evolution combined with computational protein design yields enzymes "
            "with 100x improved catalytic efficiency for biofuel production. Deep learning "
            "models predict beneficial mutations with 78% accuracy, reducing screening "
            "cycles from 12 to 3."
        ),
        "keywords": ["protein engineering", "enzyme", "directed evolution", "deep learning", "biofuel"],
    },
    {
        "doc_id": "BIO-006", "title": "Neural Circuit Mapping in Drosophila",
        "source": "Neuron, 2024",
        "content": (
            "Using electron microscopy and connectomics, we map the complete neural circuit "
            "for olfactory learning in Drosophila melanogaster. The circuit contains 347 "
            "neurons and 2,891 synapses. Ablation experiments confirm the critical role "
            "of mushroom body output neurons in associative memory."
        ),
        "keywords": ["neuroscience", "neural circuits", "connectomics", "Drosophila", "olfactory"],
    },
]

UPLOADS = [
    (CS_PAPERS,  "cs"),
    (BIO_PAPERS, "bio"),
]

STACK_NAME = "lesson-08-demo-rag"


def get_bucket_name() -> str:
    """Look up the S3 bucket name from the CloudFormation stack output."""
    cf = boto3.client("cloudformation", region_name=AWS_REGION)
    try:
        resp = cf.describe_stacks(StackName=STACK_NAME)
        outputs = resp["Stacks"][0].get("Outputs", [])
        for o in outputs:
            if o["OutputKey"] == "KBSourceBucketName":
                return o["OutputValue"]
    except Exception as e:
        print(f"ERROR: Could not find stack '{STACK_NAME}': {e}")
        print("Make sure you deployed the CloudFormation stack first.")
        sys.exit(1)
    print(f"ERROR: KBSourceBucketName output not found in stack '{STACK_NAME}'.")
    sys.exit(1)


def doc_to_text(doc: dict) -> str:
    """Format a document dict as a plain-text file for Bedrock KB ingestion."""
    keywords = ", ".join(doc.get("keywords", []))
    return (
        f"Title: {doc['title']}\n"
        f"Source: {doc['source']}\n"
        f"Keywords: {keywords}\n\n"
        f"{doc['content']}\n"
    )


def seed(bucket: str):
    s3 = boto3.client("s3", region_name=AWS_REGION)
    total = 0
    for docs, prefix in UPLOADS:
        for doc in docs:
            key = f"{prefix}/{doc['doc_id']}.txt"
            body = doc_to_text(doc).encode("utf-8")
            s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType="text/plain")
            print(f"  uploaded s3://{bucket}/{key}")
            total += 1
    print(f"\nDone. {total} documents uploaded.")
    print("\nNext step: open the Bedrock console and create your Knowledge Bases.")
    print("Point each KB at the matching S3 prefix:")
    print(f"  CS Papers:       s3://{bucket}/cs/")
    print(f"  Biology Papers:  s3://{bucket}/bio/")


if __name__ == "__main__":
    print(f"Looking up S3 bucket from CloudFormation stack '{STACK_NAME}'...")
    bucket = get_bucket_name()
    print(f"Bucket: {bucket}\n")
    print("Uploading documents...")
    seed(bucket)
