from user_agents import parse

# Family and version come from the User-Agent header, which the caller controls.
# The version in particular is free text, so without a bound a crafted header
# decides the length of a value we persist and cluster on. Bounding here keeps
# every signal short regardless of what any individual column allows.
_MAX_FAMILY = 32
_MAX_MAJOR = 5


def _family(value) -> str:
    """Family name, bounded. Falls back to "Unknown" when absent."""
    return (str(value)[:_MAX_FAMILY] if value else "") or "Unknown"


def _major(value) -> str:
    """Major version, or "Unknown" when it is not a plausible one.

    A real major version is a short integer. Anything else is junk from a
    crafted header, and reporting it as unknown keeps it out of the clustering
    features rather than admitting a fabricated version that looks real.
    """
    text = str(value) if value else "Unknown"
    return text if text.isdigit() and len(text) <= _MAX_MAJOR else "Unknown"


class UserAgentInfo:
    """
    A class to parse and extract detailed user agent information.

    Attributes:
        _obj: The parsed user agent object.
    """

    def __init__(self, user_agent_str: str) -> None:
        """
        Initializes the UserAgentInfo class with a user agent string.

        Args:
            user_agent_str (str): The user agent string from a request.
        """

        self._obj = parse(user_agent_str)

    def get_detailed(self) -> dict:
        """
        Extracts detailed device, OS, and browser information from the user
        agent string.

        Returns:
            dict: A dictionary containing device, OS, browser, and device type
            details.
        """

        try:
            return {
                "device": {
                    "family": self._obj.device.family or "Unknown",
                    "brand": self._obj.device.brand or "Unknown",
                    "model": self._obj.device.model or "Unknown",
                },
                "operating_system": {
                    "family": self._obj.os.family or "Unknown",
                    "version_string": self._obj.os.version_string or "Unknown",
                    "version": self._obj.os.version or "Unknown",
                },
                "browser": {
                    "family": self._obj.browser.family or "Unknown",
                    "version_string": self._obj.browser.version_string or "Unknown",
                    "version": self._obj.browser.version or "Unknown",
                },
                "device_type": {
                    "is_mobile": self._obj.is_mobile,
                    "is_tablet": self._obj.is_tablet,
                    "is_touch_capable": self._obj.is_touch_capable,
                    "is_pc": self._obj.is_pc,
                    "is_bot": self._obj.is_bot,
                },
            }
        except Exception as e:
            return {"error": str(e)}

    def get_device(self) -> str:
        """
        Get a string representation of the device.

        Returns:
            str: The device family, brand, and model.
        """

        return (
            f"{self._obj.device.family or 'Unknown'}"
            + f"|{self._obj.device.brand or 'Unknown'}"
            + f"|{self._obj.device.model or 'Unknown'}"
        )

    def get_device_family(self) -> str:
        """
        Get the device family.

        Returns:
            str: The device family.
        """

        return self._obj.device.family or "Unknown"

    def get_device_brand(self) -> str:
        """
        Get the device brand.

        Returns:
            str: The device brand.
        """

        return self._obj.device.brand or "Unknown"

    def get_device_model(self) -> str:
        """
        Get the device model.

        Returns:
            str: The device model.
        """

        return self._obj.device.model or "Unknown"

    def get_operating_system(self) -> str:
        """
        Get a string representation of the operating system.

        Returns:
            str: The OS family and version string.
        """

        return (
            f"{self._obj.os.family or 'Unknown'}"
            + f"|{self.get_operating_system_version_info().get('major') or 'Unknown'}"
        )

    def get_operating_system_family(self) -> str:
        """
        Get the operating system family.

        Returns:
            str: The OS family.
        """

        return self._obj.os.family or "Unknown"

    def get_browser(self) -> str:
        """
        Get a string representation of the browser.

        Returns:
            str: The browser family and version string.
        """

        return (
            f"{self._obj.browser.family or 'Unknown'}"
            + f"|{self._obj.browser.version_string or 'Unknown'}"
        )

    def get_browser_family(self) -> str:
        """
        Get the browser family.

        Returns:
            str: The browser family.
        """

        return _family(self._obj.browser.family)

    def get_device_type(self) -> str:
        """
        Get the type of device (e.g., mobile, tablet, PC, bot).

        Returns:
            str: The type of device.
        """

        if self._obj.is_pc:
            return "pc"

        if self._obj.is_mobile:
            return "mobile"

        if self._obj.is_bot:
            return "bot"

        if self._obj.is_tablet:
            return "tablet"

        return "Unknown"

    def get_operating_system_version_info(self) -> dict:
        """
        Extracts the major, minor, and patch version numbers for the operating
        system.

        Returns:
            dict: A dictionary containing the operating system's 'major',
            'minor', and 'patch' version numbers.
        """

        os_version = self._obj.os.version or []

        major = os_version[0] if len(os_version) > 0 else "Unknown"
        minor = os_version[1] if len(os_version) > 1 else "Unknown"
        patch = os_version[2] if len(os_version) > 2 else "Unknown"

        return {"major": major, "minor": minor, "patch": patch}

    def get_browser_version_info(self) -> dict:
        """
        Extracts the major, minor, and patch version numbers for the browser.

        Returns:
            dict: A dictionary containing the browser's 'major', 'minor', and
            'patch' version numbers.
        """

        browser_version = self._obj.browser.version or []

        major = browser_version[0] if len(browser_version) > 0 else "Unknown"
        minor = browser_version[1] if len(browser_version) > 1 else "Unknown"
        patch = browser_version[2] if len(browser_version) > 2 else "Unknown"

        return {"major": major, "minor": minor, "patch": patch}

    def get_browser_family_major(self) -> str:
        """
        Retrieve browser family and its major version.

        Returns:
            str: Browser family and major version separated by '|'.
        """
        browser_version_info = self.get_browser_version_info()
        return (
            f"{_family(self._obj.browser.family)}"
            f"|{_major(browser_version_info.get('major'))}"
        )

    def get_os_family_major(self) -> str:
        """
        Retrieve operating system family and its major version.

        Returns:
            str: OS family and major version separated by '|'.
        """
        os_version_info = self.get_operating_system_version_info()
        return (
            f"{_family(self._obj.os.family)}"
            f"|{_major(os_version_info.get('major'))}"
        )

    def get_browser_signal(self, include_version: bool) -> str:
        """
        Browser value used as a risk signal.

        Args:
            include_version: When True, return family and major version
                ("Chrome|150"); when False, return the family only ("Chrome").
                Family-only avoids treating routine browser auto-updates as a
                changed signal. The caller supplies the value from
                ``DEVICE_SIGNAL_INCLUDE_BROWSER_VERSION`` so this parser stays
                free of configuration.

        Returns:
            str: The browser signal string.
        """
        return self.get_browser_family_major() if include_version else self.get_browser_family()
