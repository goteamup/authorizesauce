from datetime import date
from unittest import TestCase

import mock
from suds import WebFault

from authorize.apis.customer import PROD_URL, TEST_URL, CustomerAPI
from authorize.data import Address, CreditCard
from authorize.exceptions import AuthorizeConnectionError, AuthorizeResponseError


class AttrDict(dict):
    def __init__(self, *args, **kwargs):
        dict.__init__(self, *args, **kwargs)
        self.__dict__ = self


OPTIONS = "x_version=3.1&x_test_request=F&x_delim_data=TRUE&x_delim_char=%3B"
RESPONSE = (
    "1;1;1;This transaction has been approved.;IKRAGJ;Y;2171062816;;;20.00;CC"
    ";auth_only;;Jeffrey;Schenck;;45 Rose Ave;Venice;CA;90291;USA;;;;;;;;;;;;"
    ";;;;;375DD9293D7605E20DF0B437EE2A7B92;P;2;;;;;;;;;;;XXXX1111;Visa;;;;;;;"
    ";;;;;;;;;;Y"
)
PARSED_RESPONSE = {
    "cvv_response": "P",
    "authorization_code": "IKRAGJ",
    "response_code": "1",
    "amount": "20.00",
    "transaction_type": "auth_only",
    "avs_response": "Y",
    "response_reason_code": "1",
    "response_reason_text": "This transaction has been approved.",
    "transaction_id": "2171062816",
}
SUCCESS = AttrDict(
    {
        "resultCode": "Ok",
        "customerProfileId": "123456",
        "customerPaymentProfileIdList": [["123457"]],
        "customerPaymentProfileId": "123458",
        "directResponse": RESPONSE,
    }
)
ERROR = AttrDict(
    {
        "resultCode": "Error",
        "messages": [
            [
                AttrDict(
                    {
                        "code": "E00016",
                        "text": "The field type is invalid.",
                    }
                )
            ]
        ],
    }
)


class CustomerAPITests(TestCase):
    def setUp(self):
        self.patcher = mock.patch("authorize.apis.customer.Client")
        self.Client = self.patcher.start()
        self.api = CustomerAPI("123", "456")

        # Make the factory creator return mocks that know what kind they are
        def create(kind):
            created = mock.Mock()
            created._kind = kind
            return created

        self.api.client.factory.create.side_effect = create

    def tearDown(self):
        self.patcher.stop()

    def test_basic_api(self):
        api = CustomerAPI("123", "456")
        self.assertEqual(api.url, TEST_URL)
        api = CustomerAPI("123", "456", debug=False)
        self.assertEqual(api.url, PROD_URL)

    def test_client_and_auth(self):
        self.Client.reset_mock()
        api = CustomerAPI("123", "456")
        self.assertEqual(self.Client.call_args, None)
        api.client
        self.assertEqual(self.Client.call_args[0][0], TEST_URL)
        client_auth = api.client_auth
        self.assertEqual(client_auth.name, "123")
        self.assertEqual(client_auth.transactionKey, "456")

    def test_make_call(self):
        self.api.client.service.TestService.return_value = SUCCESS
        result = self.api._make_call("TestService", "foo")
        self.assertEqual(result, SUCCESS)
        self.assertEqual(
            self.api.client.service.TestService.call_args[0],
            (self.api.client_auth, "foo"),
        )

    def test_make_call_connection_error(self):
        self.api.client.service.TestService.side_effect = WebFault("a", "b")
        self.assertRaises(
            AuthorizeConnectionError, self.api._make_call, "TestService", "foo"
        )
        self.assertEqual(
            self.api.client.service.TestService.call_args[0],
            (self.api.client_auth, "foo"),
        )

    def test_make_call_response_error(self):
        self.api.client.service.TestService.return_value = ERROR
        try:
            self.api._make_call("TestService", "foo")
        except AuthorizeResponseError as e:
            self.assertEqual(str(e), "E00016: The field type is invalid.")
        self.assertEqual(
            self.api.client.service.TestService.call_args[0],
            (self.api.client_auth, "foo"),
        )

    def test_create_saved_profile(self):
        service = self.api.client.service.CreateCustomerProfile
        service.return_value = SUCCESS

        # Without payments
        profile_id, payment_ids = self.api.create_saved_profile(123)
        profile = service.call_args[0][1]
        self.assertEqual(profile._kind, "CustomerProfileType")
        self.assertEqual(profile.merchantCustomerId, 123)
        self.assertNotEqual(
            profile.paymentProfiles._kind, "ArrayOfCustomerPaymentProfileType"
        )
        self.assertEqual(profile_id, "123456")
        self.assertEqual(payment_ids, None)

        # With payments
        payment = mock.Mock()
        profile_id, payment_ids = self.api.create_saved_profile(123, [payment])
        profile = service.call_args[0][1]
        self.assertEqual(profile._kind, "CustomerProfileType")
        self.assertEqual(profile.merchantCustomerId, 123)
        self.assertEqual(
            profile.paymentProfiles._kind, "ArrayOfCustomerPaymentProfileType"
        )
        self.assertEqual(profile.paymentProfiles.CustomerPaymentProfileType, [payment])
        self.assertEqual(profile_id, "123456")
        self.assertEqual(payment_ids, ["123457"])

    def test_create_saved_payment(self):
        service = self.api.client.service.CreateCustomerPaymentProfile
        service.return_value = SUCCESS
        year = date.today().year + 10
        credit_card = CreditCard("4111111111111111", year, 1, "911", "Jeff", "Schenck")
        address = Address("45 Rose Ave", "Venice", "CA", "90291")

        # Without profile id should return object
        payment_profile = self.api.create_saved_payment(credit_card, address)
        self.assertEqual(service.call_args, None)
        self.assertEqual(payment_profile._kind, "CustomerPaymentProfileType")
        self.assertEqual(payment_profile.payment._kind, "PaymentType")
        self.assertEqual(payment_profile.payment.creditCard._kind, "CreditCardType")
        self.assertEqual(
            payment_profile.payment.creditCard.cardNumber, "4111111111111111"
        )
        self.assertEqual(
            payment_profile.payment.creditCard.expirationDate, "{0}-01".format(year)
        )
        self.assertEqual(payment_profile.payment.creditCard.cardCode, "911")
        self.assertEqual(payment_profile.billTo.firstName, "Jeff")
        self.assertEqual(payment_profile.billTo.lastName, "Schenck")
        self.assertEqual(payment_profile.billTo.address, "45 Rose Ave")
        self.assertEqual(payment_profile.billTo.city, "Venice")
        self.assertEqual(payment_profile.billTo.state, "CA")
        self.assertEqual(payment_profile.billTo.zip, "90291")
        self.assertEqual(payment_profile.billTo.country, "US")

        # With profile id should make call to API
        payment_profile_id = self.api.create_saved_payment(credit_card, profile_id="1")
        self.assertEqual(payment_profile_id, "123458")
        self.assertEqual(service.call_args[0][1], "1")
        payment_profile = service.call_args[0][2]
        self.assertEqual(payment_profile._kind, "CustomerPaymentProfileType")
        self.assertEqual(payment_profile.payment._kind, "PaymentType")
        self.assertEqual(payment_profile.payment.creditCard._kind, "CreditCardType")
        self.assertEqual(
            payment_profile.payment.creditCard.cardNumber, "4111111111111111"
        )
        self.assertEqual(
            payment_profile.payment.creditCard.expirationDate, "{0}-01".format(year)
        )
        self.assertEqual(payment_profile.payment.creditCard.cardCode, "911")
        self.assertEqual(payment_profile.billTo.firstName, "Jeff")
        self.assertEqual(payment_profile.billTo.lastName, "Schenck")
        self.assertNotEqual(payment_profile.billTo.address, "45 Rose Ave")
        self.assertNotEqual(payment_profile.billTo.city, "Venice")
        self.assertNotEqual(payment_profile.billTo.state, "CA")
        self.assertNotEqual(payment_profile.billTo.zip, "90291")
        self.assertNotEqual(payment_profile.billTo.country, "US")

    def test_delete_saved_profile(self):
        service = self.api.client.service.DeleteCustomerProfile
        service.return_value = SUCCESS
        self.api.delete_saved_profile("1")
        self.assertEqual(service.call_args[0][1], "1")

    def test_delete_saved_payment(self):
        service = self.api.client.service.DeleteCustomerPaymentProfile
        service.return_value = SUCCESS
        self.api.delete_saved_payment("1", "2")
        self.assertEqual(service.call_args[0][1:], ("1", "2"))

    def test_auth(self):
        service = self.api.client.service.CreateCustomerProfileTransaction
        service.return_value = SUCCESS
        result = self.api.auth("1", "2", 20)
        transaction, options = service.call_args[0][1:]
        self.assertEqual(transaction._kind, "ProfileTransactionType")
        self.assertEqual(
            transaction.profileTransAuthOnly._kind, "ProfileTransAuthOnlyType"
        )
        self.assertEqual(transaction.profileTransAuthOnly.amount, "20.00")
        self.assertEqual(transaction.profileTransAuthOnly.customerProfileId, "1")
        self.assertEqual(transaction.profileTransAuthOnly.customerPaymentProfileId, "2")
        self.assertEqual(options, OPTIONS)
        self.assertEqual(result, PARSED_RESPONSE)

    def test_capture(self):
        service = self.api.client.service.CreateCustomerProfileTransaction
        service.return_value = SUCCESS
        result = self.api.capture("1", "2", 20)
        transaction, options = service.call_args[0][1:]
        self.assertEqual(transaction._kind, "ProfileTransactionType")
        self.assertEqual(
            transaction.profileTransAuthCapture._kind, "ProfileTransAuthCaptureType"
        )
        self.assertEqual(transaction.profileTransAuthCapture.amount, "20.00")
        self.assertEqual(transaction.profileTransAuthCapture.customerProfileId, "1")
        self.assertEqual(
            transaction.profileTransAuthCapture.customerPaymentProfileId, "2"
        )
        self.assertEqual(options, OPTIONS)
        self.assertEqual(result, PARSED_RESPONSE)
