import 'package:flutter/material.dart';

import '../gateway/models.dart';

/// A grouped evidence section with one card per graph node or raw chunk.
final class EvidenceCards extends StatefulWidget {
  const EvidenceCards({
    super.key,
    required this.evidence,
  });

  final List<EvidenceItem> evidence;

  @override
  State<EvidenceCards> createState() => _EvidenceCardsState();
}

final class _EvidenceCardsState extends State<EvidenceCards> {
  bool _expanded = true;

  @override
  Widget build(BuildContext context) {
    if (widget.evidence.isEmpty) return const SizedBox.shrink();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Divider(height: 28),
        TextButton.icon(
          onPressed: () => setState(() => _expanded = !_expanded),
          icon: Icon(_expanded ? Icons.expand_less : Icons.expand_more),
          label: const Text('Evidence'),
          style: TextButton.styleFrom(
            alignment: Alignment.centerLeft,
            padding: const EdgeInsets.symmetric(vertical: 12),
          ),
        ),
        if (_expanded)
          ...widget.evidence.map(
            (item) => Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: _EvidenceCard(item: item),
            ),
          ),
      ],
    );
  }
}

final class _EvidenceCard extends StatelessWidget {
  const _EvidenceCard({required this.item});

  final EvidenceItem item;

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: switch (item) {
          GraphNodeEvidence evidence => _GraphCard(evidence: evidence),
          UnprocessedEvidence evidence => _ChunkCard(evidence: evidence),
        },
      ),
    );
  }
}

final class _GraphCard extends StatelessWidget {
  const _GraphCard({required this.evidence});

  final GraphNodeEvidence evidence;

  @override
  Widget build(BuildContext context) {
    final node = evidence.node;
    final title = _nodeTitle(node);
    final description = _nodeDescription(node, title);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Wrap(
          spacing: 8,
          runSpacing: 6,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            Chip(label: Text(node.table)),
            Text(
              node.id,
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ],
        ),
        const SizedBox(height: 4),
        Text(title, style: Theme.of(context).textTheme.titleMedium),
        if (description.isNotEmpty) ...[
          const SizedBox(height: 4),
          Text(description),
        ],
        if (evidence.links.isNotEmpty) ...[
          const Divider(height: 24),
          ...evidence.links.map((link) => _LinkRow(link: link)),
        ],
      ],
    );
  }
}

final class _LinkRow extends StatelessWidget {
  const _LinkRow({required this.link});

  final LinkedEdge link;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(
            Icons.arrow_forward,
            size: 18,
            color: Theme.of(context).colorScheme.primary,
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('${link.table}: ${link.from} → ${link.to}'),
                if (link.context != null && link.context!.isNotEmpty)
                  Text(
                    link.context!,
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

final class _ChunkCard extends StatelessWidget {
  const _ChunkCard({required this.evidence});

  final UnprocessedEvidence evidence;

  @override
  Widget build(BuildContext context) {
    final chunk = evidence.chunk;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Wrap(
          spacing: 8,
          runSpacing: 6,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            Chip(
              avatar: const Icon(Icons.pending_outlined, size: 16),
              label: const Text('Unprocessed'),
            ),
            Text(
              chunk.id,
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ],
        ),
        const SizedBox(height: 4),
        Text(chunk.content),
        const SizedBox(height: 10),
        Text(
          '${chunk.source} · chunk ${chunk.chunkPosition + 1} of ${chunk.totalChunks}',
          style: Theme.of(context).textTheme.bodySmall,
        ),
        if (chunk.hints.isNotEmpty)
          Text(
            'Hints: ${chunk.hints.join(', ')}',
            style: Theme.of(context).textTheme.bodySmall,
          ),
      ],
    );
  }
}

String _nodeTitle(GraphNode node) {
  if (node.name?.isNotEmpty == true) return node.name!;
  if (node.summary?.isNotEmpty == true) return node.summary!;
  if (node.content?.isNotEmpty == true) {
    final firstSentence = node.content!.split(RegExp(r'[.!?]')).first.trim();
    if (firstSentence.isNotEmpty) return firstSentence;
  }
  return node.id;
}

String _nodeDescription(GraphNode node, String title) {
  final value = node.description ?? node.content ?? node.summary ?? '';
  return value == title ? '' : value;
}
