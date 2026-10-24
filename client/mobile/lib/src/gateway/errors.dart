/// Base exception crossing the mobile gateway boundary.
sealed class BrainClientException implements Exception {
  const BrainClientException(this.message);

  final String message;
}

/// A request could not reach the server or receive a response.
final class NetworkException extends BrainClientException {
  const NetworkException(super.message);
}

/// The server returned a non-success HTTP status.
final class HttpStatusException extends BrainClientException {
  const HttpStatusException({
    required this.statusCode,
    required String message,
    this.body,
  }) : super(message);

  final int statusCode;
  final String? body;
}

/// The server response did not satisfy the gateway response contract.
final class MalformedResponseException extends BrainClientException {
  const MalformedResponseException(super.message);
}
