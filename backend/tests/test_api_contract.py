import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from app.core.api_errors import ApiError
from app.core.exception_handlers import setup_exception_handlers
from app.core.middleware import RequestIdMiddleware


class InputModel(BaseModel):
    name: str = Field(min_length=3)


class ApiContractTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.add_middleware(RequestIdMiddleware)
        setup_exception_handlers(app)

        @app.get("/business-error")
        async def business_error():
            raise ApiError(409, "STATE_CONFLICT", "状态冲突")

        @app.post("/validate")
        async def validate(payload: InputModel):
            return payload

        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()

    def test_business_error_has_request_id_and_standard_shape(self):
        response = self.client.get(
            "/business-error",
            headers={"X-Request-ID": "client-request-123"},
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.headers["X-Request-ID"], "client-request-123")
        self.assertEqual(
            response.json(),
            {
                "code": "STATE_CONFLICT",
                "message": "状态冲突",
                "field_errors": [],
                "request_id": "client-request-123",
            },
        )

    def test_validation_errors_identify_the_field(self):
        response = self.client.post("/validate", json={"name": "x"})

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], "VALIDATION_ERROR")
        self.assertEqual(response.json()["field_errors"][0]["field"], "name")
        self.assertEqual(
            response.headers["X-Request-ID"],
            response.json()["request_id"],
        )


if __name__ == "__main__":
    unittest.main()
