import '../gateway/models.dart';

String memoryTitle(GraphNode node) => _memoryTitle(node, 'Untitled memory');

String connectedMemoryTitle(GraphNode? node) =>
    node == null ? 'Connected memory' : _memoryTitle(node, 'Connected memory');

String _memoryTitle(GraphNode node, String fallback) {
  final name = node.name?.trim() ?? '';
  if (name.isNotEmpty) return name;

  final summary = node.summary?.trim() ?? '';
  if (summary.isNotEmpty) return summary;

  final sentence = (node.content ?? '')
      .split(RegExp(r'[.!?](?:\s|$)'))
      .first
      .trim()
      .replaceAll(RegExp(r'\s+'), ' ');
  if (sentence.isEmpty) return fallback;
  if (sentence.length <= 100) return sentence;

  final prefix = sentence.substring(0, 99);
  final lastSpace = prefix.lastIndexOf(' ');
  final shortened = lastSpace > 0 ? prefix.substring(0, lastSpace) : prefix;
  return '${shortened.trimRight()}…';
}

String memoryKind(GraphNode node) {
  return switch (node.table.trim().toLowerCase()) {
    'note' => 'Note',
    'entity' || 'concept' => 'Concept',
    _ => 'Memory',
  };
}

String relationshipTitle(LinkedEdge edge) {
  final words = edge.table.replaceAll(RegExp(r'[_\s]+'), ' ').trim();
  if (words.isEmpty) return 'Connection';
  return '${words[0].toUpperCase()}${words.substring(1)}';
}
