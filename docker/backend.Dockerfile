FROM python:3.12.8-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir \
      svgelements==1.9.6 shapely==2.1.2 ezdxf==1.4.4 Flask==3.1.3 \
      openai==2.54.0 gunicorn==23.0.0 pyproj==3.7.2 \
    && pip install --no-cache-dir --no-deps .
COPY site/index.json ./site/index.json
COPY site/map-data ./site/map-data
COPY site/svgs ./site/svgs
COPY site/dxfs ./site/dxfs
COPY data ./data
RUN useradd --system --uid 10001 --create-home appuser \
    && chown -R appuser:appuser /app
USER 10001
CMD ["gunicorn", "--workers", "1", "--threads", "4", "--bind", "0.0.0.0:8000", "--timeout", "70", "svg2dxf.server.app:create_app()"]
