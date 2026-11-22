# API Prompts for LinkedIn Vacancy Classification System

This directory contains three API-ready prompt templates for classifying and validating LinkedIn job vacancies using OpenRouter and Claude APIs.

## Files

### 1. openrouter_classification_prompt.md
**Purpose**: Classify LinkedIn vacancies using OpenRouter API

**Key Features**:
- Classifies into 6 role families (creatividad_diseno, contenido_social, marketing_growth, pr_comunicaciones, estrategia_cuentas, OTHER)
- Assesses 6 seniority levels (junior, specialist, senior, lead, manager, director)
- Evaluates AI involvement (0-3 scale: none, implicit, explicit, structural)
- Produces confidence-scored outputs (0.0-1.0)
- Includes 3 detailed examples

**Output Format**: JSON with role_family, seniority, ai_level, ai_tools_detected, ai_keywords_detected, confidence, reasoning

**Usage**: Copy the system instructions into OpenRouter API calls for batch vacancy classification

---

### 2. openrouter_skills_extraction_prompt.md
**Purpose**: Extract and categorize skills from job descriptions using OpenRouter

**Key Features**:
- Categorizes skills into 5 types (hard_skills, soft_skills, strategic_skills, ai_operational_skills, ai_cognitive_skills)
- Provides text excerpts showing where skills are mentioned
- Assigns individual confidence scores per skill
- Includes 2 detailed examples showing all 5 categories
- 30+ example skills across categories

**Output Format**: JSON array of skills with name, category, context_excerpt, confidence

**Usage**: Copy system instructions for skill extraction in OpenRouter API calls

---

### 3. claude_validation_prompt.md
**Purpose**: Validate OpenRouter classifications using Claude API

**Key Features**:
- 5-point validation checklist (role family, seniority, AI level, skills, drift indicators)
- 3 validation result types (APPROVED, NEEDS_REVIEW, REJECTED)
- Drift detection (overclassification, skill anomalies, AI level mismatches, etc.)
- Confidence adjustment guidance
- Includes 3 detailed examples showing different outcomes

**Output Format**: JSON with validation_result, feedback, corrections, confidence_adjustment, drift_indicators

**Usage**: Use as Claude API prompt for quality assurance and error detection

---

## Integration Guide

### For OpenRouter Classification
```
1. Prepare vacancy data (vacancy_id, raw_title, raw_description, raw_requirements, company_name, country)
2. Use openrouter_classification_prompt.md system instructions
3. Call OpenRouter API with the prompt and vacancy data
4. Parse returned JSON classification
```

### For OpenRouter Skills Extraction
```
1. Prepare job description (vacancy_id, raw_description, raw_requirements)
2. Use openrouter_skills_extraction_prompt.md system instructions
3. Call OpenRouter API with the prompt and job data
4. Parse returned JSON array of skills
```

### For Claude Validation
```
1. Collect OpenRouter classification and extracted skills from above steps
2. Use claude_validation_prompt.md system instructions
3. Call Claude API with the prompt and classification data
4. Parse validation result and apply corrections as needed
```

---

## Key Specifications

### Role Families
- **creatividad_diseno**: Design, UX/UI, visual content, design systems
- **contenido_social**: Social media, community management, social content
- **marketing_growth**: Growth marketing, performance, conversion optimization
- **pr_comunicaciones**: PR, communications, media relations, messaging
- **estrategia_cuentas**: Account management, customer success, ABM
- **OTHER**: Roles not fitting above categories

### Seniority Levels
- **junior**: 0-2 years, execution-focused
- **specialist**: 2-5 years, deep expertise in specific area
- **senior**: 5-10 years, broad expertise, mentoring
- **lead**: 7-12 years, owns domain, leads small teams
- **manager**: 8+ years, manages 5-15 people
- **director**: 12+ years, manages managers, 15+ people

### AI Levels (0-3 Scale)
- **0 (None)**: No AI tools mentioned
- **1 (Implicit)**: MarTech/CRM with built-in AI (HubSpot, Salesforce, Google Analytics)
- **2 (Explicit)**: Direct AI tools (ChatGPT, Claude, Gemini, Copilot)
- **3 (Structural)**: AI-native (prompt engineering, agents, fine-tuning)

### Skill Categories
- **hard_skills**: Tools, languages, technical skills
- **soft_skills**: Communication, leadership, collaboration
- **strategic_skills**: Vision, strategy, business thinking
- **ai_operational_skills**: Prompting, automation, tool usage
- **ai_cognitive_skills**: Output evaluation, curation, validation

---

## Quality Notes

- All JSON schemas are exact and copy-paste ready
- Examples are concrete and fully populated
- Edge cases are documented with handling rules
- Confidence rules are clearly defined
- Outputs are validated for parseable JSON
- All prompts are production-ready for API integration

---

## Files Statistics
- **Total Lines**: 1,098
- **Total Size**: ~49KB
- **Examples**: 8 (3 classification, 2 skills extraction, 3 validation)
- **Edge Cases Covered**: 15+
- **JSON Schemas**: 6 (input/output specs)
