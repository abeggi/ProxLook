#!/bin/bash
# Docker build script for ProxLook

set -e

# Default values
IMAGE_NAME="proxlook"
IMAGE_TAG="latest"
NO_CACHE=false
PUSH=false
REGISTRY=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --name)
            IMAGE_NAME="$2"
            shift 2
            ;;
        --tag)
            IMAGE_TAG="$2"
            shift 2
            ;;
        --no-cache)
            NO_CACHE=true
            shift
            ;;
        --push)
            PUSH=true
            shift
            ;;
        --registry)
            REGISTRY="$2"
            shift 2
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo "Build ProxLook Docker image"
            echo ""
            echo "Options:"
            echo "  --name NAME      Image name (default: proxlook)"
            echo "  --tag TAG        Image tag (default: latest)"
            echo "  --no-cache       Build without cache"
            echo "  --push           Push to registry after build"
            echo "  --registry URL   Registry URL (e.g., docker.io/username)"
            echo "  --help           Show this help"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Build arguments
BUILD_ARGS=""
if [ "$NO_CACHE" = true ]; then
    BUILD_ARGS="$BUILD_ARGS --no-cache"
fi

# Full image name
if [ -n "$REGISTRY" ]; then
    FULL_IMAGE_NAME="$REGISTRY/$IMAGE_NAME:$IMAGE_TAG"
else
    FULL_IMAGE_NAME="$IMAGE_NAME:$IMAGE_TAG"
fi

echo "🔨 Building ProxLook Docker image..."
echo "   Image: $FULL_IMAGE_NAME"
echo "   Args: $BUILD_ARGS"

# Build the image
docker build $BUILD_ARGS -t "$FULL_IMAGE_NAME" .

echo "✅ Build completed: $FULL_IMAGE_NAME"

# Push if requested
if [ "$PUSH" = true ]; then
    if [ -z "$REGISTRY" ]; then
        echo "❌ Error: Cannot push without registry. Use --registry option."
        exit 1
    fi
    
    echo "🚀 Pushing image to registry..."
    docker push "$FULL_IMAGE_NAME"
    echo "✅ Push completed"
fi

# Show available commands
echo ""
echo "📦 Available commands:"
echo "   docker run -p 8090:8090 $FULL_IMAGE_NAME"
echo "   docker-compose up -d"
echo ""