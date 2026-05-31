# Exercise Starter: Content Moderation Pipeline

## Architecture

![Architecture Diagram](architecture.svg)

This folder contains the starter code for the Module 2 exercise.

## File
- `content_moderation.py` — Partially implemented. Students must complete 3 TODOs.

## TODOs
1. **TODO 1:** Create BedrockModel with Nova Lite and return screening Agent
2. **TODO 2:** Create BedrockModel with Claude and return deep review Agent
3. **TODO 3:** Create BedrockModel with Nova Pro and return notice Agent

## Pre-Written Code
- All 3 tool functions (screen_post, deep_review_post, generate_notice)
- Sample data (9 posts, screening rules, deep review verdicts, notice templates)
- Main function with conditional routing logic and latency reporting

## Setup

1. Copy the env template: `cp .env.example .env`
2. Ensure AWS credentials are loaded (use the "Load AWS Credentials" sidebar in the Udacity lab).


## How to Run
```bash
python content_moderation.py
```
