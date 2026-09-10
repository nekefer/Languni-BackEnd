import unittest
from unittest.mock import MagicMock

from src.auth.models import RegisterUserRequest
from src.auth.service import register_user
from src.exceptions import UserAlreadyExistsError


class RegistrationTests(unittest.TestCase):
    def test_existing_email_returns_conflict(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = object()
        request = RegisterUserRequest(
            email="existing@example.com",
            first_name="Existing",
            last_name="User",
            password="Secure1!",
        )

        with self.assertRaises(UserAlreadyExistsError) as raised:
            register_user(db, request)

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.detail, "A user with this email already exists.")
        db.add.assert_not_called()


if __name__ == "__main__":
    unittest.main()
