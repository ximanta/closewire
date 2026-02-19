#!/bin/bash

# CloseWire - Quick Start Script

echo "🎯 CloseWire: Architecture for the Cognitive Enterprise"
echo "======================================================="
echo ""

# Check if Gemini API key is set
if [ -z "$GEMINI_API_KEY" ]; then
    echo "❌ ERROR: GEMINI_API_KEY not set"
    echo "Please set your Gemini API key in your environment or .env file"
    echo "export GEMINI_API_KEY='your-key-here'"
    exit 1
fi

echo "✅ Gemini API key found"
echo ""

# Backend setup
echo "🔧 Setting up backend..."
cd backend

if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

echo "Activating virtual environment..."
source venv/bin/activate

echo "Installing dependencies..."
pip install -r requirements.txt --quiet

echo "✅ Backend ready"
echo ""

# Start backend in background
echo "🚀 Starting backend server (FastAPI)..."
python main.py &
BACKEND_PID=$!
echo "Backend running on http://localhost:8000 (PID: $BACKEND_PID)"
echo ""

# Frontend setup
echo "🔧 Setting up frontend..."
cd ../frontend

if [ ! -d "node_modules" ]; then
    echo "Installing frontend dependencies..."
    npm install --silent
fi

echo "✅ Frontend ready"
echo ""

# Start frontend
echo "🚀 Starting frontend (React)..."
echo "Frontend will run on http://localhost:3000"
echo ""
echo "======================================================="
echo "✅ CloseWire is running!"
echo "Open http://localhost:3000 in your browser"
echo ""
echo "To stop: Press Ctrl+C"
echo "======================================================="
echo ""

npm start

# Cleanup on exit
kill $BACKEND_PID
