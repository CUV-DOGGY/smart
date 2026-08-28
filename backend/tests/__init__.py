import os


# Tests must be reproducible without a developer's ignored backend/.env file.
_TEST_ENVIRONMENT = {
    "MODEL_NAME": "test-model",
    "DEEPSEEK_API_KEY": "test-api-key",
    "DEEPSEEK_BASE_URL": "https://example.invalid/v1",
    "AMAP_WEB_SERVICE_KEY": "test-amap-key",
    "JWT_SECRET_KEY": "test-jwt-secret-key-at-least-32-characters",
    "RATE_LIMIT_KEY_SECRET": "test-rate-limit-key-at-least-32-characters",
}

# Live integrations are explicitly authorized by the caller and must use the
# developer's real environment/.env settings. Offline tests keep deterministic
# placeholders and never contact external services.
if os.getenv("RUN_LLM_INTEGRATION") != "1":
    for _name, _value in _TEST_ENVIRONMENT.items():
        os.environ.setdefault(_name, _value)
