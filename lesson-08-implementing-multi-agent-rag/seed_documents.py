"""
seed_documents.py
=================
Uploads all Knowledge Base source documents to S3.

Run this ONCE after deploying the CloudFormation stack and BEFORE
creating the Knowledge Bases in the Bedrock console.

Usage:
    python seed_documents.py

The bucket name is read from the CloudFormation stack output automatically.
Requires AWS credentials with S3 write access.
"""

import boto3
import sys

# ── Document Content ──────────────────────────────────────────────────────────
# These are the exact documents that should be indexed in each Knowledge Base.
# Each document is uploaded as a .txt file under the correct S3 prefix.

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

DRUG_INTERACTIONS_KB = [
    {
        "doc_id": "DI-001", "title": "Warfarin-Aspirin Interaction Profile",
        "source": "Clinical Pharmacology & Therapeutics, 2024",
        "content": (
            "Concurrent use of warfarin and aspirin increases bleeding risk by 2.5x. "
            "The mechanism involves dual anticoagulant/antiplatelet pathways. INR monitoring "
            "should be increased to weekly when co-prescribing. Consider dose reduction of "
            "warfarin by 25% with low-dose aspirin (81mg)."
        ),
        "keywords": ["warfarin", "aspirin", "bleeding", "anticoagulant", "drug interaction", "INR"],
    },
    {
        "doc_id": "DI-002", "title": "Metformin and Contrast Dye: Lactic Acidosis Risk",
        "source": "Journal of Clinical Pharmacology, 2024",
        "content": (
            "Metformin should be withheld 48 hours before and after iodinated contrast "
            "procedures. Risk of lactic acidosis is elevated in patients with eGFR < 30. "
            "For patients with eGFR 30-60, hold metformin 24 hours pre-procedure. "
            "Monitor serum creatinine 48 hours post-procedure before resuming."
        ),
        "keywords": ["metformin", "contrast dye", "lactic acidosis", "renal", "drug interaction"],
    },
    {
        "doc_id": "DI-003", "title": "SSRI-MAOI Interaction: Serotonin Syndrome",
        "source": "Annals of Pharmacotherapy, 2024",
        "content": (
            "Combining SSRIs with MAOIs can cause life-threatening serotonin syndrome. "
            "Symptoms include hyperthermia (>40°C), muscle rigidity, and autonomic instability. "
            "A 14-day washout period is required when switching between these drug classes. "
            "Fluoxetine requires a 5-week washout due to its long half-life."
        ),
        "keywords": ["SSRI", "MAOI", "serotonin syndrome", "antidepressant", "drug interaction"],
    },
    {
        "doc_id": "DI-004", "title": "Statin-Grapefruit Interaction Mechanisms",
        "source": "Drug Metabolism Reviews, 2024",
        "content": (
            "Grapefruit juice inhibits CYP3A4, increasing statin plasma levels 2-16x. "
            "Simvastatin and lovastatin are most affected (CYP3A4 substrates). "
            "Atorvastatin is moderately affected. Pravastatin and rosuvastatin are "
            "unaffected. Advise patients on statins to avoid grapefruit consumption."
        ),
        "keywords": ["statin", "grapefruit", "CYP3A4", "drug interaction", "metabolism"],
    },
    {
        "doc_id": "DI-005", "title": "Warfarin-Amiodarone: High-Risk Combination",
        "source": "Heart Rhythm, 2024",
        "content": (
            "Amiodarone inhibits CYP2C9 and CYP3A4, increasing warfarin effect by 30-50%. "
            "Reduce warfarin dose by 33-50% when initiating amiodarone. INR can remain "
            "elevated for weeks after amiodarone discontinuation due to its 40-55 day "
            "half-life. Weekly INR monitoring for 3 months recommended."
        ),
        "keywords": ["warfarin", "amiodarone", "CYP2C9", "anticoagulant", "drug interaction"],
    },
    {
        "doc_id": "DI-006", "title": "ACE Inhibitor-Potassium Supplement Hyperkalemia",
        "source": "American Journal of Medicine, 2024",
        "content": (
            "ACE inhibitors reduce aldosterone secretion, causing potassium retention. "
            "Co-administration with potassium supplements or potassium-sparing diuretics "
            "increases hyperkalemia risk 3x. Monitor serum potassium within 1 week of "
            "starting ACE inhibitor. Target K+ level: 3.5-5.0 mEq/L."
        ),
        "keywords": ["ACE inhibitor", "potassium", "hyperkalemia", "drug interaction"],
    },
]

CLINICAL_GUIDELINES_KB = [
    {
        "doc_id": "CG-001", "title": "AHA/ACC Guideline: Anticoagulation for Atrial Fibrillation",
        "source": "Circulation, 2024 AHA/ACC Guidelines",
        "content": (
            "For non-valvular AF with CHA2DS2-VASc >= 2, recommend DOACs over warfarin "
            "(Class I, Level A). If warfarin is used, target INR 2.0-3.0 with time in "
            "therapeutic range >= 70%. Bleeding risk assessment using HAS-BLED score "
            "should guide anticoagulation decisions. Annual reassessment required."
        ),
        "keywords": ["anticoagulation", "atrial fibrillation", "warfarin", "DOAC", "guideline", "bleeding"],
    },
    {
        "doc_id": "CG-002", "title": "ADA Standards: Metformin as First-Line for Type 2 Diabetes",
        "source": "Diabetes Care, 2024 ADA Standards",
        "content": (
            "Metformin remains first-line pharmacotherapy for type 2 diabetes (Grade A). "
            "Start at 500mg daily, titrate to 2000mg over 4 weeks. Monitor renal function "
            "(eGFR) at baseline and annually. Contraindicated if eGFR < 30. Reduce dose "
            "to 1000mg/day if eGFR 30-45."
        ),
        "keywords": ["metformin", "diabetes", "first-line", "renal", "guideline"],
    },
    {
        "doc_id": "CG-003", "title": "APA Guidelines: SSRI Prescribing for Major Depression",
        "source": "American Journal of Psychiatry, 2024 APA Guidelines",
        "content": (
            "SSRIs recommended as first-line for moderate-severe MDD (Level I evidence). "
            "Start at lowest effective dose. Allow 4-6 weeks for full response. "
            "If inadequate response, augment with bupropion or switch to SNRI. "
            "MAOIs reserved for treatment-resistant cases with 14-day washout from SSRIs."
        ),
        "keywords": ["SSRI", "depression", "antidepressant", "MAOI", "guideline", "prescribing"],
    },
    {
        "doc_id": "CG-004", "title": "ACC/AHA Statin Therapy Guidelines",
        "source": "Journal of the ACC, 2024 Guidelines",
        "content": (
            "High-intensity statins (atorvastatin 40-80mg, rosuvastatin 20-40mg) recommended "
            "for patients with ASCVD or LDL >= 190mg/dL (Class I, Level A). Moderate-intensity "
            "for primary prevention in adults 40-75 with diabetes. Monitor LDL 4-12 weeks "
            "after initiation. Target >= 50% LDL reduction for high-intensity."
        ),
        "keywords": ["statin", "cholesterol", "ASCVD", "LDL", "guideline", "prevention"],
    },
    {
        "doc_id": "CG-005", "title": "JNC 8: Hypertension Management with ACE Inhibitors",
        "source": "JAMA, 2024 JNC Guidelines Update",
        "content": (
            "ACE inhibitors first-line for hypertension in patients with diabetes or CKD. "
            "Start lisinopril 10mg daily, target BP < 130/80. Monitor potassium and "
            "creatinine within 1-2 weeks of initiation. Contraindicated in pregnancy. "
            "If persistent cough, switch to ARB."
        ),
        "keywords": ["ACE inhibitor", "hypertension", "guideline", "potassium", "renal"],
    },
    {
        "doc_id": "CG-006", "title": "WHO Guidelines: Antibiotic Stewardship",
        "source": "WHO Essential Medicines, 2024",
        "content": (
            "Narrow-spectrum antibiotics preferred over broad-spectrum when pathogen is "
            "identified (Strong recommendation). Culture and sensitivity testing before "
            "empiric therapy when feasible. De-escalation within 48-72 hours based on "
            "culture results. Duration: shortest effective course."
        ),
        "keywords": ["antibiotic", "stewardship", "resistance", "guideline", "prescribing"],
    },
]

# ── S3 Upload ─────────────────────────────────────────────────────────────────

UPLOADS = [
    (CS_PAPERS,              "cs"),
    (BIO_PAPERS,             "bio"),
    (DRUG_INTERACTIONS_KB,   "drugs"),
    (CLINICAL_GUIDELINES_KB, "guidelines"),
]

STACK_NAME = "lesson-08-rag"


def get_bucket_name() -> str:
    """Look up the S3 bucket name from the CloudFormation stack output."""
    cf = boto3.client("cloudformation")
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
    s3 = boto3.client("s3")
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
    print(f"  Demo  — CS Papers:           s3://{bucket}/cs/")
    print(f"  Demo  — Biology Papers:       s3://{bucket}/bio/")
    print(f"  Exer  — Drug Interactions:    s3://{bucket}/drugs/")
    print(f"  Exer  — Clinical Guidelines:  s3://{bucket}/guidelines/")


if __name__ == "__main__":
    print(f"Looking up S3 bucket from CloudFormation stack '{STACK_NAME}'...")
    bucket = get_bucket_name()
    print(f"Bucket: {bucket}\n")
    print("Uploading documents...")
    seed(bucket)
