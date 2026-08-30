#!/bin/bash
# ==============================================================================
# H.A.T.S 24/7 Cloud Deployment Script (Ubuntu / Debian / AWS EC2 / DigitalOcean)
# ==============================================================================
set -e

echo "🚀 Starting H.A.T.S Automated Cloud Deployment..."

# 1. Update system packages
sudo apt-get update && sudo apt-get upgrade -y
sudo apt-get install -y curl git ca-certificates gnupg lsb-release cron

# 2. Install Docker if not already present
if ! command -v docker &> /dev/null; then
    echo "📦 Installing Docker Engine & Docker Compose Plugin..."
    sudo mkdir -p /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
      $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    sudo apt-get update
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
    sudo usermod -aG docker $USER
    echo "✅ Docker installed successfully."
fi

# 3. Create .env if not present
if [ ! -f config/.env ]; then
    echo "⚙️ Creating config/.env from example template..."
    cp config/.env.example config/.env
    echo "⚠️ Please edit config/.env to add your real Alpaca and Gemini API keys:"
    echo "   nano config/.env"
fi

# 4. Set up 4:05 PM ET (20:05 UTC) Daily Trading Cycle Cron Job
CRON_JOB="5 20 * * 1-5 cd $(pwd) && docker compose exec -T dashboard python -m src.main --interval 1d >> /var/log/hats_daily.log 2>&1"
(crontab -l 2>/dev/null | grep -v "src.main" ; echo "$CRON_JOB") | crontab -
echo "✅ Registered Daily Trading Cycle cron job at 4:05 PM US Eastern Time (Mon-Fri)."

# 5. Build and launch Docker Compose services
echo "🐳 Launching H.A.T.S Dashboard & Database containers..."
docker compose up --build -d

echo ""
echo "=============================================================================="
echo "🎉 H.A.T.S Cloud Deployment Complete!"
echo "• Web Dashboard & Copilot: http://<YOUR_SERVER_IP>:8000"
echo "• Database (TimescaleDB):  localhost:5432"
echo "• Daily Trading Cycle:     4:05 PM US Eastern (Automated Cron)"
echo "=============================================================================="
