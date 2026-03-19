"""UW SIS Registration API client wrapper.

This module provides a client interface for interacting with the
University of Washington Student Information System (SIS) Registration API.
"""

from typing import Any, Literal, TypeAlias, cast

import requests

from cache import RegistrationCache
from constants import (
    API_BASE_URL,
    DEFAULT_CACHE_MAX_AGE_SECONDS,
    DEFAULT_GRADING_SYSTEM,
    DEFAULT_HEADERS,
    ERROR_EMPTY_PAYLOAD,
    ERROR_EMPTY_SLN_LIST,
    ERROR_MISSING_SECURITY_TOKENS,
    ERROR_NOT_AUTHENTICATED,
    ERROR_SWAP_MISSING_SLNS,
    ERROR_UNEXPECTED_MYPLAN_FORMAT,
    HEADER_CHECKSUM,
    HEADER_CSRF,
    REGISTRATION_ACTION_ADD,
    REGISTRATION_ACTION_DROP,
    SESSION_COOKIE_DOMAIN,
    SESSION_COOKIE_NAME,
)

# Type aliases for API responses
RegistrationResponse: TypeAlias = dict[str, Any]


class NotAuthenticatedError(PermissionError):
    """Exception raised when client is not authenticated."""

    def __init__(self) -> None:
        """Initialize the exception with standard message."""
        super().__init__(ERROR_NOT_AUTHENTICATED)


class MissingSecurityTokensError(ValueError):
    """Exception raised when security tokens are missing from session response."""

    def __init__(self) -> None:
        """Initialize the exception with standard message."""
        super().__init__(ERROR_MISSING_SECURITY_TOKENS)


class EmptySLNListError(ValueError):
    """Exception raised when SLN list is empty."""

    def __init__(self) -> None:
        """Initialize the exception with standard message."""
        super().__init__(ERROR_EMPTY_SLN_LIST)


class EmptyPayloadError(ValueError):
    """Exception raised when registration payload is empty."""

    def __init__(self) -> None:
        """Initialize the exception with standard message."""
        super().__init__(ERROR_EMPTY_PAYLOAD)


class SwapMissingSLNsError(ValueError):
    """Exception raised when swap operation is missing required SLNs."""

    def __init__(self) -> None:
        """Initialize the exception with standard message."""
        super().__init__(ERROR_SWAP_MISSING_SLNS)


class UnexpectedMyPlanFormatError(TypeError):
    """Exception raised when MyPlan response format is unexpected."""

    def __init__(self) -> None:
        """Initialize the exception with standard message."""
        super().__init__(ERROR_UNEXPECTED_MYPLAN_FORMAT)


class UWAPI:
    """A client wrapper for the UW SIS Registration API."""

    def __init__(self, session_id: str) -> None:
        """Initialize API client with session ID.

        Args:
            session_id: The authentication session ID cookie value.

        """
        self.base_url: str = API_BASE_URL
        self.session: requests.Session = requests.Session()
        self.cache: RegistrationCache = RegistrationCache()

        # Set the initial session cookie
        cookie_jar = cast("Any", self.session.cookies)
        cookie_jar.set(
            SESSION_COOKIE_NAME,
            session_id,
            domain=SESSION_COOKIE_DOMAIN,
        )

        # Set base headers required by the API Gateway / CORS
        self.session.headers.update(DEFAULT_HEADERS)

        # Internal state initialized during authentication
        self.is_authenticated: bool = False
        self.student_number: str | None = None
        self.reg_id: str | None = None

    def authenticate(self) -> bool:
        """Fetch session data and extract security tokens.

        Retrieves CSRF and checksum tokens from the session endpoint and
        updates request headers. Also extracts user identity for later use.

        Returns:
            True if authentication successful, False otherwise.

        """
        try:
            response = self.session.get(f"{self.base_url}/api/session")
            response.raise_for_status()
            data = response.json()

            # Extract security tokens
            checksum = data.get("application", {}).get("checksum")
            csrf_token = data.get("csrf")

            if not checksum or not csrf_token:
                raise MissingSecurityTokensError

            # Bind tokens to all future requests
            self.session.headers.update(
                {HEADER_CHECKSUM: checksum, HEADER_CSRF: csrf_token},
            )

            # Extract user identity parameters (often required in POST payloads)
            user_data = data.get("user", {})
            self.student_number = user_data.get("studentNumber")
            self.reg_id = user_data.get("regId")

            self.is_authenticated = True
        except (requests.RequestException, MissingSecurityTokensError) as e:
            print(f"Authentication failed: {e}")
            self.is_authenticated = False
            return False
        else:
            return True

    def get_registration(
        self,
        quarter_code: str,
        *,
        use_cache: bool = True,
        max_age_seconds: int = DEFAULT_CACHE_MAX_AGE_SECONDS,
    ) -> dict[str, Any]:
        """Retrieve registration data for a specific quarter.

        Uses a local cache by default to reduce API calls.

        Args:
            quarter_code: Quarter code in YYYYQ format (e.g., '20262').
            use_cache: Whether to use cached data if available.
            max_age_seconds: Maximum age of cached data in seconds.

        Returns:
            Dictionary containing registration data for the quarter.

        Raises:
            NotAuthenticatedError: If client is not authenticated.

        """
        if not self.is_authenticated:
            raise NotAuthenticatedError

        response_data, _ = self._get_registration_internal(
            quarter_code=quarter_code,
            use_cache=use_cache,
            max_age_seconds=max_age_seconds,
        )
        return response_data

    def get_registration_with_source(
        self,
        quarter_code: str,
        *,
        use_cache: bool = True,
        max_age_seconds: int = DEFAULT_CACHE_MAX_AGE_SECONDS,
    ) -> tuple[dict[str, Any], Literal["cache", "api"]]:
        """Return registration payload and source (cache or api).

        Args:
            quarter_code: Quarter code in YYYYQ format (e.g., '20262').
            use_cache: Whether to use cached data if available.
            max_age_seconds: Maximum age of cached data in seconds.

        Returns:
            Tuple of (registration_data, source) where source is 'cache' or 'api'.

        Raises:
            NotAuthenticatedError: If client is not authenticated.

        """
        if not self.is_authenticated:
            raise NotAuthenticatedError

        return self._get_registration_internal(
            quarter_code=quarter_code,
            use_cache=use_cache,
            max_age_seconds=max_age_seconds,
        )

    def _get_registration_internal(
        self,
        quarter_code: str,
        *,
        use_cache: bool,
        max_age_seconds: int,
    ) -> tuple[dict[str, Any], Literal["cache", "api"]]:
        """Fetch registration data and return payload with source label.

        Args:
            quarter_code: Quarter code in YYYYQ format.
            use_cache: Whether to check cache first.
            max_age_seconds: Maximum age of cached data.

        Returns:
            Tuple of (registration_data, source).

        """
        if use_cache:
            cached_data = self.cache.get_registration(quarter_code, max_age_seconds)
            if cached_data is not None:
                return cached_data, "cache"

        response = self.session.get(f"{self.base_url}/api/registration/{quarter_code}")
        response.raise_for_status()
        response_data = response.json()

        self.cache.save_registration(quarter_code, response_data)

        return response_data, "api"

    @staticmethod
    def _normalize_slns(slns: list[str]) -> list[str]:
        """Normalize and validate a list of SLNs.

        Args:
            slns: List of SLN strings to normalize.

        Returns:
            List of normalized SLN strings (stripped and non-empty).

        Raises:
            EmptySLNListError: If no valid SLNs remain after normalization.

        """
        normalized_slns = [sln.strip() for sln in slns if sln and sln.strip()]
        if not normalized_slns:
            raise EmptySLNListError
        return normalized_slns

    def add_courses(
        self,
        quarter_code: str,
        slns: list[str],
        grading_system: str = DEFAULT_GRADING_SYSTEM,
    ) -> RegistrationResponse:
        """Submit add-course registration changes for one or more SLNs.

        Args:
            quarter_code: Quarter code in YYYYQ format.
            slns: List of SLN strings to register.
            grading_system: Grading system code (default: "0").

        Returns:
            API response from registration endpoint.

        Raises:
            EmptySLNListError: If SLN list is empty after normalization.

        """
        normalized_slns = self._normalize_slns(slns)

        payload: list[dict[str, Any]] = [
            {
                "action": REGISTRATION_ACTION_ADD,
                "section": {"sln": sln},
                "gradingSystem": grading_system,
            }
            for sln in normalized_slns
        ]

        return self.submit_registration_changes(
            quarter_code=quarter_code,
            payload=payload,
        )

    def _build_drop_entry(
        self,
        sln: str,
        registration: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build a drop registration entry from registration data.

        Args:
            sln: The SLN to drop.
            registration: Optional full registration record.

        Returns:
            Dictionary representing a drop action for the registration API.

        """
        if not isinstance(registration, dict):
            return {"action": REGISTRATION_ACTION_DROP, "section": {"sln": sln}}

        drop_entry: dict[str, Any] = {
            "action": REGISTRATION_ACTION_DROP,
            **registration,
        }
        section: dict[str, Any] = drop_entry.get("section", {})
        if not section:
            section = {"sln": sln}
        if not section.get("sln"):
            section["sln"] = sln
        drop_entry["section"] = section

        if "gradingSystem" not in drop_entry or not drop_entry.get("gradingSystem"):
            drop_entry["gradingSystem"] = DEFAULT_GRADING_SYSTEM
        return drop_entry

    def drop_courses(
        self,
        quarter_code: str,
        slns: list[str],
        drop_registrations: list[dict[str, Any]] | None = None,
    ) -> RegistrationResponse:
        """Submit drop-course registration changes for one or more SLNs.

        Args:
            quarter_code: Quarter code in YYYYQ format.
            slns: List of SLN strings to drop.
            drop_registrations: Optional list of full registration records.

        Returns:
            API response from registration endpoint.

        Raises:
            EmptySLNListError: If SLN list is empty after normalization.

        """
        normalized_slns = self._normalize_slns(slns)

        payload: list[dict[str, Any]]
        if isinstance(drop_registrations, list) and drop_registrations:
            registration_by_sln: dict[str, dict[str, Any]] = {}
            for registration in drop_registrations:
                section: dict[str, Any] = registration.get("section", {})
                if not section:
                    continue
                reg_sln = str(section.get("sln", "")).strip()
                if reg_sln:
                    registration_by_sln[reg_sln] = registration

            payload = [
                self._build_drop_entry(sln, registration_by_sln.get(sln))
                for sln in normalized_slns
            ]
        else:
            payload = [
                {"action": REGISTRATION_ACTION_DROP, "section": {"sln": sln}}
                for sln in normalized_slns
            ]

        return self.submit_registration_changes(
            quarter_code=quarter_code,
            payload=payload,
        )

    def swap_classes(
        self,
        quarter_code: str,
        drop_sln: str,
        add_sln: str,
        drop_registration: dict[str, Any] | None = None,
    ) -> RegistrationResponse:
        """Submit a swap request: add one SLN and drop one existing course.

        Args:
            quarter_code: Quarter code in YYYYQ format.
            drop_sln: SLN of the course to drop.
            add_sln: SLN of the course to add.
            drop_registration: Optional full registration record for the drop.

        Returns:
            API response from registration endpoint.

        Raises:
            SwapMissingSLNsError: If either drop_sln or add_sln is missing.

        """
        normalized_drop_sln = drop_sln.strip()
        normalized_add_sln = add_sln.strip()
        if not normalized_drop_sln or not normalized_add_sln:
            raise SwapMissingSLNsError

        drop_entry = self._build_drop_entry(normalized_drop_sln, drop_registration)

        payload: list[dict[str, Any]] = [
            {
                "action": REGISTRATION_ACTION_ADD,
                "section": {"sln": normalized_add_sln},
                "gradingSystem": DEFAULT_GRADING_SYSTEM,
            },
            drop_entry,
        ]

        return self.submit_registration_changes(
            quarter_code=quarter_code,
            payload=payload,
        )

    def submit_registration_changes(
        self,
        quarter_code: str,
        payload: list[dict[str, Any]],
    ) -> RegistrationResponse:
        """Submit registration change payload to the registration endpoint.

        Args:
            quarter_code: Quarter code in YYYYQ format.
            payload: List of registration actions to submit.

        Returns:
            JSON response from the API, or dict with status code and text.

        Raises:
            NotAuthenticatedError: If client is not authenticated.
            EmptyPayloadError: If payload is empty.

        """
        if not self.is_authenticated:
            raise NotAuthenticatedError

        if not payload:
            raise EmptyPayloadError

        response = self.session.post(
            f"{self.base_url}/api/registration/{quarter_code}",
            json=payload,
        )
        response.raise_for_status()

        self.cache.invalidate(quarter_code)

        try:
            return response.json()
        except ValueError:
            return {
                "statusCode": response.status_code,
                "text": response.text,
            }

    def add_course(self, quarter_code: str, sln: str) -> RegistrationResponse:
        """Register one SLN (compatibility wrapper).

        Args:
            quarter_code: Quarter code in YYYYQ format.
            sln: SLN to register.

        Returns:
            API response from registration endpoint.

        """
        return self.add_courses(quarter_code=quarter_code, slns=[sln])

    def get_myplan_terms(
        self,
        term_id: str,
        *,
        validate: bool = True,
        include_academic_history: bool = True,
    ) -> list[dict[str, Any]]:
        """Fetch MyPlan term data for a specific term id.

        Args:
            term_id: Term ID in YYYYQ format (e.g., '20262').
            validate: Whether to validate the plan.
            include_academic_history: Whether to include academic history.

        Returns:
            List of MyPlan term data dictionaries.

        Raises:
            NotAuthenticatedError: If client is not authenticated.
            UnexpectedMyPlanFormatError: If response is not a list.

        """
        if not self.is_authenticated:
            raise NotAuthenticatedError

        response = self.session.get(
            f"{self.base_url}/api/plan/terms",
            params={
                "termId": term_id,
                "validate": str(validate).lower(),
                "includeAcademicHistory": str(include_academic_history).lower(),
            },
        )
        response.raise_for_status()

        payload = response.json()
        if not isinstance(payload, list):
            raise UnexpectedMyPlanFormatError
        return cast("list[dict[str, Any]]", payload)
