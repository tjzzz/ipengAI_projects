#!/usr/bin/env python3
"""
Payment adapter — abstracts payment gateway integration.
Uses the Adapter pattern so the app can switch between mock and real payment providers.
"""

from abc import ABC, abstractmethod
import os
import logging

logger = logging.getLogger(__name__)


class PaymentAdapter(ABC):
    """Interface for payment gateway adapters."""

    @abstractmethod
    def create_payment(self, order_id, amount, description):
        """
        Create a payment order (legacy method).
        Returns a dict with payment_url and method info.
        """
        pass

    @abstractmethod
    def verify_payment(self, payment_token):
        """
        Verify that a payment was completed successfully (legacy method).
        Returns True if valid, False otherwise.
        """
        pass

    # ========== New methods for real payment integration ==========

    def create_prepay_order(self, order_id, amount, description, **kwargs):
        """
        Create a prepay order and return QR code for scanning.
        Returns dict with qr_code, order_id, and payment info.
        Default: raises NotImplementedError (adapters must implement if supported).
        """
        raise NotImplementedError("This adapter does not support prepay orders")

    def verify_notification(self, params, signature=None):
        """
        Verify payment notification from payment gateway.
        Returns (is_valid, order_id, trade_no, amount) tuple.
        Default: raises NotImplementedError.
        """
        raise NotImplementedError("This adapter does not support notifications")

    def query_payment(self, order_id):
        """
        Query payment status from gateway (active polling).
        Returns dict with status and payment details.
        Default: raises NotImplementedError.
        """
        raise NotImplementedError("This adapter does not support status queries")


class MockPaymentAdapter(PaymentAdapter):
    """Mock payment adapter for development/testing — simulates payment flow."""

    def create_payment(self, order_id, amount, description):
        """Return a simulated payment URL."""
        return {"payment_url": f"/mock-pay/{order_id}", "method": "mock"}

    def verify_payment(self, payment_token):
        """Accept any token starting with 'PAY-'."""
        return bool(payment_token and payment_token.startswith("PAY-"))

    def create_prepay_order(self, order_id, amount, description, **kwargs):
        """Simulate a prepay order with a mock QR code."""
        # Generate a mock QR code string (in real Alipay, this would be like:
        # https://qr.alipay.com/bax00xxx)
        mock_qr = f"MOCK_QR_{order_id}_{int(amount * 100)}"
        return {
            "qr_code": mock_qr,
            "order_id": order_id,
            "amount": amount,
            "method": "mock",
            "expires_in": 1800
        }

    def verify_notification(self, params, signature=None):
        """Accept mock notifications with valid format."""
        # Mock: accept if out_trade_no and trade_status are present
        order_id = params.get("out_trade_no")
        trade_status = params.get("trade_status")
        if order_id and trade_status == "TRADE_SUCCESS":
            return True, order_id, f"MOCK_TRADE_{order_id}", params.get("total_amount", 0)
        return False, None, None, None

    def query_payment(self, order_id):
        """Simulate querying payment status."""
        # Mock: always return pending (in real flow, webhook handles the update)
        return {
            "order_id": order_id,
            "trade_status": "WAIT_BUYER_PAY",
            "status": "pending"
        }


class AlipayPaymentAdapter(PaymentAdapter):
    """
    Alipay Face-to-Face Payment (当面付) adapter.
    Uses alipay-sdk-python for API calls.
    """

    def __init__(self, app_id, pid, private_key, alipay_public_key,
                 gateway_url="https://openapi.alipay.com/gateway.do",
                 notify_url=None, return_url=None):
        """
        Initialize Alipay adapter with credentials.

        Args:
            app_id: Alipay application ID
            pid: Partner ID (seller ID)
            private_key: Application private key (PKCS8 format)
            alipay_public_key: Alipay public key for signature verification
            gateway_url: Alipay gateway URL (sandbox vs production)
            notify_url: Async notification URL (webhook)
            return_url: Sync return URL after payment
        """
        self.app_id = app_id
        self.pid = pid
        self.private_key = private_key
        self.alipay_public_key = alipay_public_key
        self.gateway_url = gateway_url
        self.notify_url = notify_url
        self.return_url = return_url

        # Lazy import to avoid hard dependency if not using Alipay
        try:
            from alipay import AliPay
            self.alipay = AliPay(
                appid=app_id,
                app_notify_url=notify_url or "",
                app_private_key_string=private_key,
                alipay_public_key_string=alipay_public_key,
                sign_type="RSA2",
                debug="sandbox" in gateway_url or "openapi.alipaydev.com" in gateway_url
            )
            self._sdk_available = True
        except ImportError:
            logger.warning("alipay-sdk-python not installed, AlipayPaymentAdapter will run in mock mode")
            self.alipay = None
            self._sdk_available = False

    def create_payment(self, order_id, amount, description):
        """Legacy method - redirects to create_prepay_order."""
        result = self.create_prepay_order(order_id, amount, description)
        return {"payment_url": result.get("qr_code", ""), "method": "alipay"}

    def verify_payment(self, payment_token):
        """Legacy method - not used for Alipay flow."""
        return False

    def create_prepay_order(self, order_id, amount, description, **kwargs):
        """
        Call alipay.trade.precreate to get QR code for scanning.

        Returns:
            dict with qr_code, order_id, amount, expires_in
        """
        if not self._sdk_available:
            # Fallback to mock if SDK not installed
            logger.warning("Alipay SDK not available, returning mock QR code")
            return {
                "qr_code": f"MOCK_ALIPAY_{order_id}",
                "order_id": order_id,
                "amount": amount,
                "method": "alipay_mock",
                "expires_in": 1800
            }

        try:
            response = self.alipay.api_alipay_trade_precreate(
                out_trade_no=order_id,
                total_amount=str(amount),
                subject=description or "AI降AI率服务",
                timeout_express="30m"  # QR code valid for 30 minutes
            )

            if response.get("code") == "10000":
                return {
                    "qr_code": response.get("qr_code"),
                    "order_id": order_id,
                    "amount": amount,
                    "method": "alipay",
                    "expires_in": 1800,
                    "raw_response": response
                }
            else:
                logger.error(f"Alipay precreate failed: {response}")
                return {
                    "error": response.get("sub_msg", response.get("msg", "创建订单失败")),
                    "code": response.get("code"),
                    "order_id": order_id
                }
        except Exception as e:
            logger.exception("Alipay precreate exception")
            return {"error": str(e), "order_id": order_id}

    def verify_notification(self, params, signature=None):
        """
        Verify Alipay async notification signature and extract payment info.

        Args:
            params: Dict of notification parameters from Alipay
            signature: Signature string (can also be in params['sign'])

        Returns:
            (is_valid, order_id, trade_no, amount) tuple
        """
        if not self._sdk_available:
            # Mock mode: accept with valid-looking params
            order_id = params.get("out_trade_no")
            if order_id and params.get("trade_status") == "TRADE_SUCCESS":
                return True, order_id, params.get("trade_no"), float(params.get("total_amount", 0))
            return False, None, None, None

        try:
            # Verify signature
            sign = signature or params.get("sign")
            sign_type = params.get("sign_type", "RSA2")

            # Convert params to sorted string for verification
            is_valid = self.alipay.verify(params, sign)

            if not is_valid:
                logger.warning(f"Alipay notification signature verification failed for {params.get('out_trade_no')}")
                return False, None, None, None

            # Verify it's for our app
            if params.get("app_id") != self.app_id:
                logger.warning(f"Alipay notification app_id mismatch: {params.get('app_id')} != {self.app_id}")
                return False, None, None, None

            # Check trade status
            trade_status = params.get("trade_status")
            if trade_status not in ("TRADE_SUCCESS", "TRADE_FINISHED"):
                logger.info(f"Alipay notification with non-success status: {trade_status}")
                return False, None, None, None

            order_id = params.get("out_trade_no")
            trade_no = params.get("trade_no")
            amount = float(params.get("total_amount", 0))

            return True, order_id, trade_no, amount

        except Exception as e:
            logger.exception("Alipay notification verification exception")
            return False, None, None, None

    def query_payment(self, order_id):
        """
        Query payment status via alipay.trade.query.
        Used for active polling when webhook is not available.

        Returns:
            dict with trade_status and payment details
        """
        if not self._sdk_available:
            return {"order_id": order_id, "trade_status": "UNKNOWN", "status": "unknown"}

        try:
            response = self.alipay.api_alipay_trade_query(out_trade_no=order_id)

            if response.get("code") == "10000":
                trade_status = response.get("trade_status", "UNKNOWN")
                return {
                    "order_id": order_id,
                    "trade_no": response.get("trade_no"),
                    "trade_status": trade_status,
                    "total_amount": float(response.get("total_amount", 0)),
                    "status": "paid" if trade_status in ("TRADE_SUCCESS", "TRADE_FINISHED") else "pending",
                    "raw_response": response
                }
            else:
                return {
                    "order_id": order_id,
                    "trade_status": "UNKNOWN",
                    "status": "unknown",
                    "error": response.get("sub_msg", response.get("msg"))
                }
        except Exception as e:
            logger.exception("Alipay query exception")
            return {"order_id": order_id, "trade_status": "ERROR", "error": str(e)}


def create_payment_adapter(config=None):
    """
    Factory function to create payment adapter based on configuration.

    Args:
        config: dict with PAYMENT_ADAPTER and related settings,
                or None to read from environment

    Returns:
        PaymentAdapter instance
    """
    if config is None:
        config = {
            "PAYMENT_ADAPTER": os.environ.get("PAYMENT_ADAPTER", "mock"),
            "ALIPAY_APP_ID": os.environ.get("ALIPAY_APP_ID", ""),
            "ALIPAY_PID": os.environ.get("ALIPAY_PID", ""),
            "ALIPAY_PRIVATE_KEY": os.environ.get("ALIPAY_PRIVATE_KEY", ""),
            "ALIPAY_PUBLIC_KEY": os.environ.get("ALIPAY_PUBLIC_KEY", ""),
            "ALIPAY_GATEWAY_URL": os.environ.get("ALIPAY_GATEWAY_URL", "https://openapi.alipay.com/gateway.do"),
            "ALIPAY_NOTIFY_URL": os.environ.get("ALIPAY_NOTIFY_URL", ""),
            "ALIPAY_RETURN_URL": os.environ.get("ALIPAY_RETURN_URL", ""),
        }

    adapter_type = config.get("PAYMENT_ADAPTER", "mock")

    if adapter_type == "alipay":
        # Validate required config
        if not config.get("ALIPAY_APP_ID"):
            logger.warning("ALIPAY_APP_ID not set, falling back to mock adapter")
            return MockPaymentAdapter()

        return AlipayPaymentAdapter(
            app_id=config["ALIPAY_APP_ID"],
            pid=config.get("ALIPAY_PID", ""),
            private_key=config.get("ALIPAY_PRIVATE_KEY", ""),
            alipay_public_key=config.get("ALIPAY_PUBLIC_KEY", ""),
            gateway_url=config.get("ALIPAY_GATEWAY_URL", "https://openapi.alipay.com/gateway.do"),
            notify_url=config.get("ALIPAY_NOTIFY_URL"),
            return_url=config.get("ALIPAY_RETURN_URL")
        )
    else:
        return MockPaymentAdapter()
