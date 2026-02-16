FROM python:3.11-slim

WORKDIR /app

# Copy all necessary files for building
COPY pyproject.toml README.md ./
COPY src/ ./src/

# Install the package
RUN pip install --no-cache-dir .

# Expose the web server port
EXPOSE 8080

# Run the MCP server
# Note: MCP communicates over stdio, web server is for canvas rendering
CMD ["canvas-mcp", "--host", "0.0.0.0", "--port", "8080"]
