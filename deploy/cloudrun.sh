#!/usr/bin/env bash
# Usage: deploy/cloudrun.sh build-py | suppliers | buyer | owner | refresh | all
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] && { set -a; . ./.env; set +a; }
P=${GOOGLE_CLOUD_PROJECT:?set GOOGLE_CLOUD_PROJECT (see .env.example)}; R=asia-south1
PN=${GCP_PROJECT_NUMBER:-$(gcloud projects describe "$P" --format="value(projectNumber)")}
AR=$R-docker.pkg.dev/$P/sauda
PY_IMAGE=$AR/sauda-py:latest
FIREBASE_APP_ID=${FIREBASE_APP_ID:-}
AUTH_MODE=${AUTH_MODE:-firebase}
# Public front door: Firebase Hosting site that proxies to owner-app and hosts the Google sign-in handler,
# so the Google account chooser says "continue to saudaai.web.app" instead of the project id.
SITE_DOMAIN=saudaai.web.app
url() { echo "https://$1-$PN.$R.run.app"; }
COMMON_ENV="GOOGLE_CLOUD_PROJECT=$P,GOOGLE_CLOUD_LOCATION=$R,GOOGLE_GENAI_USE_VERTEXAI=true,GEMINI_MODEL=gemini-3.5-flash,KMS_KEY_NAME=projects/$P/locations/global/keyRings/sauda/cryptoKeys/sauda-mandates,MODEL_ARMOR_TEMPLATE=projects/$P/locations/us-central1/templates/sauda-guard,DEMO_SHOP_ID=demo,PRIVATE_BUCKET=$P-sauda-private"

build_py() {
  gcloud builds submit --project $P --region $R --config deploy/cloudbuild.yaml \
    --substitutions=_DOCKERFILE=deploy/Dockerfile.python,_IMAGE=$PY_IMAGE .
}

suppliers() {
  for s in metro sharma quickstock; do
    gcloud run deploy supplier-$s --project $P --region $R --image $PY_IMAGE \
      --service-account supplier@$P.iam.gserviceaccount.com --no-allow-unauthenticated \
      --command sh --args="-c,python -m supplier_agent.main" \
      --set-env-vars "$COMMON_ENV,SUPPLIER_PROFILE=$s,PUBLIC_URL=$(url supplier-$s)" \
      $( [ $s = sharma ] && echo "--set-secrets=PAYOUT_VPA=sharma-payout-vpa:latest" ) \
      --cpu 1 --memory 512Mi --min-instances 0 --max-instances 2 --quiet &
  done
  wait
  for s in metro sharma quickstock; do
    gcloud run services add-iam-policy-binding supplier-$s --project $P --region $R \
      --member serviceAccount:buyer-agent@$P.iam.gserviceaccount.com --role roles/run.invoker >/dev/null
    echo "supplier-$s -> $(url supplier-$s)"
  done
}

buyer() {
  gcloud run deploy buyer-agent --project $P --region $R --image $PY_IMAGE \
    --service-account buyer-agent@$P.iam.gserviceaccount.com --allow-unauthenticated \
    --set-env-vars "^@^${COMMON_ENV//,/@}@SUPPLIER_URLS=metro=$(url supplier-metro),sharma=$(url supplier-sharma),quickstock=$(url supplier-quickstock)@OWNER_APP_ORIGIN=$(url owner-app),https://$SITE_DOMAIN,https://saudaai.firebaseapp.com@AUTH_MODE=${AUTH_MODE:-demo}@DEMO_PAY_AMOUNT_PAISE=${DEMO_PAY_AMOUNT_PAISE:-100}@AGENT_MODE=${AGENT_MODE:-adk}" \
    --set-secrets "DATA_GOV_IN_API_KEY=data-gov-in-api-key:latest,DEMO_OWNER_TOKEN=demo-owner-token:latest" \
    --cpu 1 --memory 1Gi --min-instances 1 --max-instances 1 --timeout 600 --quiet
  echo "buyer-agent -> $(url buyer-agent)"
}

owner() {
  local subs="_DOCKERFILE=deploy/Dockerfile.owner-app@_IMAGE=$AR/owner-app:latest@_BUILD_ARGS_1=--build-arg=NEXT_PUBLIC_API_BASE=$(url buyer-agent)"
  if [ "${AUTH_MODE:-demo}" = firebase ]; then
    # Firebase web config is public by design; no owner token is baked into the bundle.
    local cfg; cfg=$(firebase apps:sdkconfig WEB "$FIREBASE_APP_ID" --project $P)
    local key; key=$(echo "$cfg" | sed -n 's/.*"apiKey": "\([^"]*\)".*/\1/p')
    subs="$subs@_BUILD_ARGS_2=--build-arg=NEXT_PUBLIC_AUTH_MODE=firebase@_BUILD_ARGS_3=--build-arg=NEXT_PUBLIC_FIREBASE_API_KEY=$key"
    subs="$subs@_BUILD_ARGS_4=--build-arg=NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN=$SITE_DOMAIN@_BUILD_ARGS_5=--build-arg=NEXT_PUBLIC_FIREBASE_PROJECT_ID=$P"
    subs="$subs@_BUILD_ARGS_6=--build-arg=NEXT_PUBLIC_FIREBASE_APP_ID=$FIREBASE_APP_ID"
  else
    local tok; tok=$(gcloud secrets versions access latest --secret demo-owner-token --project $P)
    subs="$subs@_BUILD_ARGS_2=--build-arg=NEXT_PUBLIC_DEMO_OWNER_TOKEN=$tok"
  fi
  gcloud builds submit --project $P --region $R --config deploy/cloudbuild.yaml --substitutions="^@^$subs" .
  gcloud run deploy owner-app --project $P --region $R --image $AR/owner-app:latest \
    --service-account owner-app@$P.iam.gserviceaccount.com --allow-unauthenticated \
    --cpu 1 --memory 512Mi --min-instances 0 --max-instances 3 --quiet
  # a new Hosting release purges the CDN cache, so the front door never serves stale HTML for old chunks
  firebase deploy --only hosting --project $P --non-interactive
  echo "owner-app -> $(url owner-app) (public: https://$SITE_DOMAIN)"
}

# Daily mandi reference-price refresh: Cloud Run job on the shared image, run by Cloud Scheduler at 11:00 and 19:00 IST.
refresh() {
  local sa=price-refresh@$P.iam.gserviceaccount.com
  gcloud iam service-accounts describe $sa --project $P >/dev/null 2>&1 || \
    gcloud iam service-accounts create price-refresh --project $P --display-name "Sauda mandi price refresh"
  gcloud projects add-iam-policy-binding $P --member serviceAccount:$sa --role roles/datastore.user --condition=None >/dev/null
  gcloud secrets add-iam-policy-binding data-gov-in-api-key --project $P --member serviceAccount:$sa --role roles/secretmanager.secretAccessor >/dev/null
  gcloud run jobs deploy price-refresh --project $P --region $R --image $PY_IMAGE --service-account $sa \
    --command python --args="-m,sauda_data.refresh" \
    --set-env-vars "GOOGLE_CLOUD_PROJECT=$P,REF_STATE=Karnataka,REF_DISTRICT=Bengaluru Urban" \
    --set-secrets "DATA_GOV_IN_API_KEY=data-gov-in-api-key:latest" \
    --cpu 1 --memory 512Mi --task-timeout 600 --max-retries 2 --quiet
  gcloud run jobs add-iam-policy-binding price-refresh --project $P --region $R --member serviceAccount:$sa --role roles/run.invoker >/dev/null
  local uri="https://run.googleapis.com/v2/projects/$P/locations/$R/jobs/price-refresh:run"
  if gcloud scheduler jobs describe price-refresh-daily --project $P --location $R >/dev/null 2>&1; then verb=update; else verb=create; fi
  gcloud scheduler jobs $verb http price-refresh-daily --project $P --location $R --schedule "0 11,19 * * *" --time-zone "Asia/Kolkata" \
    --uri "$uri" --http-method POST --oauth-service-account-email $sa --quiet
  echo "price-refresh job + schedule (11:00, 19:00 IST) ready"
}

case "${1:-all}" in
  build-py) build_py ;;
  suppliers) suppliers ;;
  buyer) buyer ;;
  owner) owner ;;
  refresh) refresh ;;
  all) build_py; suppliers; buyer; owner; refresh ;;
esac
