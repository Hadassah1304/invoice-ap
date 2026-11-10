#!/usr/bin/env bash
# ==============================================================================
# Azure Container Apps (ACA) Provisioning Script for Invoice AP Automation
# Deploys container image from Docker Hub with SQLite pre-seeded and ingress enabled.
# ==============================================================================

set -e

# Configuration (Modify or pass as env vars)
RESOURCE_GROUP="${RESOURCE_GROUP:-rg-invoice-ap}"
LOCATION="${LOCATION:-eastus}"
ACA_ENV="${ACA_ENV:-cae-invoice-ap}"
APP_NAME="${APP_NAME:-app-invoice-ap}"
DOCKERHUB_USERNAME="${DOCKERHUB_USERNAME:-ep23btech11005}"
PORT="8000"

IMAGE_REPO="${IMAGE_REPO:-$DOCKERHUB_USERNAME/invoice-ap}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
FULL_IMAGE="docker.io/$IMAGE_REPO:$IMAGE_TAG"

if [ -z "$EXPLABS_API_KEY" ]; then
    read -sp "Enter your EXPLABS_API_KEY: " EXPLABS_API_KEY
    echo ""
fi

# Optional: Private Docker Hub repository token
if [ -z "$DOCKERHUB_TOKEN" ]; then
    read -sp "Enter Docker Hub Access Token / Password (press Enter if repo is PUBLIC): " DOCKERHUB_TOKEN
    echo ""
fi

echo "========================================================================"
echo " Starting Azure Container Apps Setup for Invoice AP Automation"
echo " Resource Group: $RESOURCE_GROUP"
echo " Location:       $LOCATION"
echo " Environment:    $ACA_ENV"
echo " App Name:       $APP_NAME"
echo " Image:          $FULL_IMAGE"
echo "========================================================================"

# 1. Verify Azure CLI is authenticated
echo "[1/6] Verifying Azure CLI login..."
az account show > /dev/null 2>&1 || {
    echo "ERROR: You are not logged into Azure CLI. Please run 'az login' first."
    exit 1
}
SUBSCRIPTION_ID=$(az account show --query id -o tsv)
echo "Using Azure Subscription: $SUBSCRIPTION_ID"

# 2. Register required Azure resource providers & extensions
echo "[2/6] Ensuring containerapp extension and providers..."
az extension add --name containerapp --upgrade --yes > /dev/null 2>&1 || true
az provider register --namespace Microsoft.App --wait > /dev/null 2>&1 || true
az provider register --namespace Microsoft.OperationalInsights --wait > /dev/null 2>&1 || true

# 3. Create Resource Group
echo "[3/6] Creating Resource Group '$RESOURCE_GROUP' in '$LOCATION'..."
az group create --name "$RESOURCE_GROUP" --location "$LOCATION" -o table

# 4. Create Container Apps Managed Environment
echo "[4/6] Creating Container Apps Environment '$ACA_ENV'..."
az containerapp env create \
    --name "$ACA_ENV" \
    --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    -o table

# 5. Build Registry Arguments (if private)
REGISTRY_ARGS=""
if [ -n "$DOCKERHUB_TOKEN" ]; then
    echo "Configuring private Docker Hub registry credentials..."
    REGISTRY_ARGS="--registry-server docker.io --registry-username $DOCKERHUB_USERNAME --registry-password $DOCKERHUB_TOKEN"
fi

# 6. Deploy Container App
echo "[5/6] Creating Container App '$APP_NAME' with external ingress on port $PORT..."
az containerapp create \
    --name "$APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --environment "$ACA_ENV" \
    --image "$FULL_IMAGE" \
    --target-port "$PORT" \
    --ingress external \
    --min-replicas 1 \
    --max-replicas 1 \
    --cpu 1.0 \
    --memory 2.0Gi \
    --secrets "explabs-api-key=$EXPLABS_API_KEY" \
    --env-vars "EXPLABS_API_KEY=secretref:explabs-api-key" \
    $REGISTRY_ARGS \
    -o table

# 7. Retrieve Live URL
FQDN=$(az containerapp show --name "$APP_NAME" --resource-group "$RESOURCE_GROUP" --query properties.configuration.ingress.fqdn -o tsv)

echo ""
echo "========================================================================"
echo "🎉 DEPLOYMENT COMPLETE!"
echo "Live URL: https://$FQDN"
echo "Health Check: https://$FQDN/api/health"
echo "========================================================================"
echo ""
echo "To reset database inside the running container at any time, run:"
echo "  az containerapp exec --name $APP_NAME --resource-group $RESOURCE_GROUP --command /app/scripts/reset_db.sh"
echo ""
echo "------------------------------------------------------------------------"
echo "To set up GitHub Actions CI/CD, create a Service Principal by running:"
echo "  az ad sp create-for-rbac --name \"sp-invoice-cicd\" --role contributor \\"
echo "    --scopes /subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP \\"
echo "    --json-auth"
echo "Copy the resulting JSON into GitHub Secret: AZURE_CREDENTIALS"
echo "And set GitHub Secrets: DOCKERHUB_USERNAME and DOCKERHUB_TOKEN"
echo "------------------------------------------------------------------------"
