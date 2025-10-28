# SecOps Feed Manager

A Google Cloud Platform (GCP) hosted service for SecOps feed management with direct integration into SOMA (Security Operations Management and Analytics).

## Overview

This repository contains the implementation of SecOps_Feed_Manager designed to run in partner GCP projects that have SOMA installed. The service collects feed data and UDM search results from customer instances and stores them in BigQuery for analysis.

## Architecture

### Deployment Pipeline
- **Source**: Commit to GitHub
- **Build**: Cloud Build detects changes and stores image in Artifact Repository
- **Deploy**: Cloud Deploy builds the image and deploys to Cloud Run

### Scheduling
The service is scheduled to run daily at 12:00 AM.

## Functionality

### Core Features
- Feed management functionality for direct integration into SOMA
- Data collection from customer SecOps instances
- UDM search query execution
- BigQuery data storage

### Data Collection Process
1. **Authentication**: Uses the same service account as SOMA
2. **Secret Management**: Accesses partner Secret Manager for customer instance backstory secret keys
3. **Customer Iteration**: Iterates over customers to collect data from SecOps
4. **Data Types Collected**:
   - Feed data from SecOps instances
   - Results from 2 UDM search queries per customer instance

### Data Structure
The collected data is structured as a dictionary with the following format:

```json
{
    "customer_name": "",
    "feed_data_var1": "",
    "feed_data_var2": "",
    "udm_data_var1": "",
    "udm_data_var2": ""
}
```

## Data Storage

### BigQuery Configuration
- **Dataset**: `SOMA-Feeds`
- **Table**: `FeedData`

### Environment Configuration
The following environment variables are required:
- `GCP_PROJECT_ID`: The GCP Project ID
- `BIGQUERY_TABLE_ID`: The BigQuery Table ID

## Prerequisites

- Partner GCP project with SOMA installed
- Secret Manager configured with customer instance backstory secret keys
- Service account with appropriate permissions for SOMA and BigQuery access

## Usage

The service runs automatically based on the configured schedule. No manual intervention is required for normal operation.

## Development

For local development or testing, ensure you have:
- Access to the partner GCP project
- Proper authentication configured
- Required environment variables set





