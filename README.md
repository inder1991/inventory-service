# inventory-service

Race-condition safe inventory management

## 🚀 Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run locally  
python src/main.py

# Server starts on http://localhost:8002
```

## 🐳 Docker

```bash
# Build image
docker build -t inventory-service:v1 .

# Run container
docker run -p 8002:8002 inventory-service:v1
```

## ☸️ Kubernetes Deployment

```bash
# Deploy with Helm
helm install inventory-service ./helm \
  --namespace ecommerce \
  --create-namespace

# Port forward to test
kubectl port-forward svc/inventory-service 8002:8002 -n ecommerce
```

## 📁 Project Structure

```
inventory-service/
├── src/
│   ├── main.py          # Application entry point
│   ├── models/          # Data models
│   ├── routes/          # API routes
│   └── utils/           # Utilities
├── tests/               # Test files
├── helm/                # Helm chart
├── Dockerfile           # Container definition
└── requirements.txt     # Python dependencies
```

## 🔧 Configuration

Environment variables:
- `DATABASE_URL` - Database connection string (if applicable)
- `PORT` - Service port (default: 8002)
- Other service-specific configs

## 🛠️ Tech Stack

- Python 3.11
- FastAPI
- SQLAlchemy (if database)
- PostgreSQL (if database)
- Pydantic

## 📊 API Documentation

Once running, visit: http://localhost:8002/docs
# inventory-service
<!-- s19.smoke.2 trigger 2026-05-09T11:28:23Z -->
trigger fresh webhook for new pod 2026-05-09T11:29:32Z
