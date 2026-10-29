import 'dart:async';

import 'package:flutter/material.dart';

import '../explore/explore_controller.dart';
import '../explore/graph_canvas.dart';
import '../gateway/brain_gateway.dart';
import '../gateway/errors.dart';
import '../gateway/models.dart';
import '../mobile_workflow.dart';
import '../persistence/models.dart';
import '../persistence/repositories.dart';
import 'graph_node_detail_screen.dart';

/// Graph workspace, memory search, and local workspace maintenance.
///
/// A controller supplied by [controller] or [controllerFuture] renders its
/// cached state immediately. Refreshes are explicit state transitions owned by
/// the controller, so a failed request cannot replace cached graph data.
final class ExploreScreen extends StatefulWidget {
  const ExploreScreen({
    super.key,
    this.brainId,
    this.brainName,
    this.gateway,
    this.workflow,
    this.controller,
    this.controllerFuture,
    this.loadController,
    this.controllerLoader,
    this.workspaces,
    this.workspaceRepository,
    this.onOpenNode,
    this.onOpenDetail,
    this.onNodeSelected,
    this.onOpenHistory,
  });

  final String? brainId;
  final String? brainName;
  final BrainGateway? gateway;
  final MobileWorkflow? workflow;
  final ExploreWorkspaceController? controller;
  final Future<ExploreWorkspaceController>? controllerFuture;
  final Future<ExploreWorkspaceController> Function()? loadController;
  final Future<ExploreWorkspaceController> Function()? controllerLoader;
  final GraphWorkspaceRepository? workspaces;
  final GraphWorkspaceRepository? workspaceRepository;
  final ValueChanged<String>? onOpenNode;
  final ValueChanged<String>? onOpenDetail;
  final ValueChanged<String>? onNodeSelected;
  final VoidCallback? onOpenHistory;

  @override
  State<ExploreScreen> createState() => _ExploreScreenState();
}

final class _ExploreScreenState extends State<ExploreScreen> {
  ExploreWorkspaceController? _controller;
  Future<ExploreWorkspaceController>? _controllerFuture;
  Object? _controllerFailure;
  Object? _searchFailure;
  MemorySearchResult? _searchResult;
  bool _searching = false;
  bool _refreshing = false;
  String _query = '';
  String? _notice;
  late final TextEditingController _searchController;
  late final FocusNode _searchFocus;

  @override
  void initState() {
    super.initState();
    _searchController = TextEditingController();
    _searchFocus = FocusNode();
    _controller = widget.controller;
    if (_controller == null) _startControllerLoad();
  }

  @override
  void didUpdateWidget(covariant ExploreScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.controller != null) {
      if (!identical(widget.controller, _controller)) {
        setState(() {
          _controller = widget.controller;
          _controllerFailure = null;
        });
      }
      return;
    }
    final profileChanged = oldWidget.brainId != widget.brainId ||
        oldWidget.workflow != widget.workflow ||
        oldWidget.gateway != widget.gateway;
    final directControllerRemoved = oldWidget.controller != widget.controller;
    if (profileChanged || directControllerRemoved) {
      setState(() {
        _controller = null;
        _controllerFailure = null;
      });
      _startControllerLoad();
    }
  }

  void _startControllerLoad() {
    _controllerFuture = widget.controllerFuture ??
        widget.loadController?.call() ??
        widget.controllerLoader?.call() ??
        _loadControllerFromWorkflow() ??
        _loadControllerFromContracts();
    unawaited(_resolveController(_controllerFuture!));
  }

  @override
  void dispose() {
    _searchController.dispose();
    _searchFocus.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final controller = _controller;
    if (controller == null) {
      if (_controllerFailure != null) return _failureBody(context);
      return const Scaffold(
        appBar: _ExploreAppBar(),
        body: Center(child: CircularProgressIndicator()),
      );
    }
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.brainName == null
            ? 'Explore'
            : 'Explore · ${widget.brainName}'),
        actions: [
          if (widget.onOpenHistory != null)
            IconButton(
              onPressed: widget.onOpenHistory,
              tooltip: 'Answer history',
              icon: const Icon(Icons.history),
            ),
        ],
      ),
      body: _body(context, controller),
    );
  }

  Widget _body(
    BuildContext context,
    ExploreWorkspaceController controller,
  ) {
    final state = controller.state;
    final nodes = state.nodes;
    final edges = state.edges;
    return RefreshIndicator(
      onRefresh: () => _refresh(controller),
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(20, 12, 20, 32),
        children: [
          Text(
            'Search your memory or follow a thread.',
            style: Theme.of(context).textTheme.bodyMedium,
          ),
          const SizedBox(height: 12),
          _searchField(context),
          if (_searchFailure != null) ...[
            const SizedBox(height: 10),
            _Notice(
              message: _messageFor(_searchFailure, fallback: 'Search failed.'),
              icon: Icons.cloud_off_outlined,
            ),
          ],
          if (_searching) ...[
            const SizedBox(height: 10),
            const LinearProgressIndicator(),
          ],
          if (_searchResult != null) _searchResults(context),
          const SizedBox(height: 18),
          Row(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Expanded(
                child: Text(
                  'Exploration workspace',
                  style: Theme.of(context).textTheme.titleMedium,
                ),
              ),
              Text(
                '${nodes.length} memories · ${edges.length} connections',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ],
          ),
          if (_notice != null) ...[
            const SizedBox(height: 10),
            _Notice(message: _notice!, icon: Icons.info_outline),
          ],
          const SizedBox(height: 10),
          Row(
            children: [
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: _refreshing
                      ? null
                      : () => unawaited(_refresh(controller)),
                  icon: _refreshing
                      ? const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.refresh),
                  label: Text(_refreshing ? 'Refreshing…' : 'Refresh'),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: OutlinedButton(
                  onPressed: nodes.any(_isMissing) || edges.any(_isMissingEdge)
                      ? () => _clearDeleted(controller)
                      : null,
                  child: const Text('Clear deleted'),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            onPressed: nodes.isEmpty && edges.isEmpty
                ? null
                : () => _clearWorkspace(controller),
            icon: const Icon(Icons.delete_sweep_outlined),
            label: const Text('Clear workspace'),
          ),
          const SizedBox(height: 12),
          if (nodes.isEmpty && edges.isEmpty)
            _EmptyWorkspace(onSearch: _focusSearch)
          else ...[
            GraphCanvas(
              state: state,
              onSelectNode: (id) => unawaited(_openNode(controller, id)),
              onSelectEdge: (id) => unawaited(_followEdge(controller, id)),
            ),
            const SizedBox(height: 10),
            Text(
              'Pan and zoom the map. Tap a node for details or a directed edge to follow it.',
              style: Theme.of(context).textTheme.bodySmall,
              textAlign: TextAlign.center,
            ),
          ],
        ],
      ),
    );
  }

  Widget _searchField(BuildContext context) {
    return TextField(
      controller: _searchController,
      focusNode: _searchFocus,
      textInputAction: TextInputAction.search,
      onChanged: (value) => _query = value,
      onSubmitted: (_) => unawaited(_search()),
      decoration: InputDecoration(
        labelText: 'Search memory',
        hintText: 'Search topics and notes',
        prefixIcon: const Icon(Icons.search),
        suffixIcon: IconButton(
          onPressed: _query.trim().isEmpty ? null : () => unawaited(_search()),
          tooltip: 'Search',
          icon: const Icon(Icons.arrow_forward),
        ),
        border: const OutlineInputBorder(),
      ),
    );
  }

  Widget _searchResults(BuildContext context) {
    final result = _searchResult!;
    if (result.nodes.isEmpty && result.unprocessed.isEmpty) {
      return Padding(
        padding: const EdgeInsets.only(top: 14),
        child: _Notice(
          message: 'No memories or raw evidence matched “$_query”.',
          icon: Icons.search_off,
        ),
      );
    }
    return Padding(
      padding: const EdgeInsets.only(top: 14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (result.nodes.isNotEmpty) ...[
            Text('Graph results',
                style: Theme.of(context).textTheme.titleSmall),
            const SizedBox(height: 6),
            ...result.nodes.map(
              (node) => Card(
                margin: const EdgeInsets.symmetric(vertical: 4),
                child: ListTile(
                  leading: const Icon(Icons.account_tree_outlined),
                  title: Text(_nodeTitle(node)),
                  subtitle: Text(node.id),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () {
                    final controller = _controller;
                    if (controller != null) {
                      unawaited(_openNode(controller, node.id));
                    }
                  },
                ),
              ),
            ),
          ],
          if (result.unprocessed.isNotEmpty) ...[
            const SizedBox(height: 12),
            Text(
              'Unprocessed evidence',
              style: Theme.of(context).textTheme.titleSmall,
            ),
            const SizedBox(height: 4),
            const Text('Raw evidence is shown here and cannot open the graph.'),
            ...result.unprocessed.map(
              (chunk) => Card(
                margin: const EdgeInsets.symmetric(vertical: 4),
                child: Padding(
                  padding: const EdgeInsets.all(14),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Text(chunk.content),
                      const SizedBox(height: 7),
                      Text(
                        '${chunk.source} · chunk ${chunk.chunkPosition + 1} of ${chunk.totalChunks}',
                        style: Theme.of(context).textTheme.bodySmall,
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }

  Future<ExploreWorkspaceController>? _loadControllerFromWorkflow() {
    final workflow = widget.workflow;
    final id = widget.brainId;
    if (workflow == null || id == null) return null;
    return workflow.visitExplore(id);
  }

  Future<ExploreWorkspaceController> _loadControllerFromContracts() {
    final id = widget.brainId;
    final workspaces = widget.workspaces ?? widget.workspaceRepository;
    final gateway = widget.gateway;
    if (id == null || workspaces == null || gateway == null) {
      return Future<ExploreWorkspaceController>.error(
        StateError(
            'Explore needs a Brain profile, gateway, and workspace repository.'),
      );
    }
    return loadExploreWorkspaceController(
      brainId: id,
      workspaces: workspaces,
      gateway: gateway,
    );
  }

  Future<void> _resolveController(
    Future<ExploreWorkspaceController> future,
  ) async {
    try {
      final controller = await future;
      if (!mounted) return;
      setState(() => _controller = controller);
    } on Object catch (error) {
      if (!mounted) return;
      setState(() => _controllerFailure = error);
    }
  }

  Future<void> _search() async {
    final gateway = widget.gateway;
    final query = _query.trim();
    if (query.isEmpty) return;
    if (gateway == null) {
      setState(() {
        _searchFailure = StateError('Search needs a connection.');
        _searchResult = null;
      });
      return;
    }
    setState(() {
      _searching = true;
      _searchFailure = null;
    });
    try {
      final result = await gateway.searchMemory(query);
      if (!mounted) return;
      setState(() {
        _searchResult = result;
        _searching = false;
      });
    } on Object catch (error) {
      if (!mounted) return;
      setState(() {
        _searchFailure = error;
        _searching = false;
        _searchResult = null;
      });
    }
  }

  Future<void> _openNode(
    ExploreWorkspaceController controller,
    String id,
  ) async {
    controller.selectNode(id);
    final callback =
        widget.onOpenNode ?? widget.onOpenDetail ?? widget.onNodeSelected;
    if (callback != null) {
      callback(id);
      return;
    }
    Object? failure;
    try {
      await controller.openNode(id);
    } on Object catch (error) {
      failure = error;
    }
    if (!mounted) return;
    if (failure != null &&
        !controller.state.nodes.any((node) => node.node.id == id)) {
      setState(() => _notice =
          _messageFor(failure, fallback: 'Could not open this memory.'));
      return;
    }
    await Navigator.of(context).push<void>(
      MaterialPageRoute<void>(
        builder: (_) => GraphNodeDetailScreen(
          controller: controller,
          nodeId: id,
          onNodeSelected: (_) {
            if (mounted) setState(() {});
          },
        ),
      ),
    );
    if (mounted) setState(() {});
  }

  Future<void> _followEdge(
    ExploreWorkspaceController controller,
    String id,
  ) async {
    try {
      await controller.followEdge(id);
      if (mounted) setState(() {});
    } on Object catch (error) {
      if (mounted) {
        setState(() => _notice =
            _messageFor(error, fallback: 'Could not follow this connection.'));
      }
    }
  }

  Future<void> _refresh(ExploreWorkspaceController controller) async {
    if (_refreshing) return;
    setState(() {
      _refreshing = true;
      _notice = null;
    });
    try {
      await controller.refresh();
      if (!mounted) return;
      setState(() {
        _refreshing = false;
        _notice = 'Workspace refreshed.';
      });
    } on Object catch (error) {
      if (!mounted) return;
      setState(() {
        _refreshing = false;
        _notice =
            _messageFor(error, fallback: 'Refresh failed. Cached graph kept.');
      });
    }
  }

  void _clearDeleted(ExploreWorkspaceController controller) {
    controller.clearDeleted();
    setState(
        () => _notice = 'Confirmed-missing items cleared from this workspace.');
  }

  Future<void> _clearWorkspace(ExploreWorkspaceController controller) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Clear workspace?'),
        content: const Text(
            'Remove this local Explore workspace? The Brain is not changed.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('Clear workspace'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    await controller.clearWorkspace();
    if (!mounted) return;
    setState(() => _notice = 'Workspace cleared.');
  }

  void _focusSearch() {
    FocusScope.of(context).requestFocus(_searchFocus);
  }

  Widget _failureBody(BuildContext context) {
    return Scaffold(
      appBar: const _ExploreAppBar(),
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.cloud_off_outlined, size: 48),
              const SizedBox(height: 12),
              const Text('Explore is unavailable.',
                  textAlign: TextAlign.center),
              const SizedBox(height: 8),
              Text(
                  _messageFor(_controllerFailure,
                      fallback: 'Could not load this workspace.'),
                  textAlign: TextAlign.center),
              const SizedBox(height: 14),
              OutlinedButton(
                onPressed: () {
                  final future = widget.controllerFuture ??
                      widget.loadController?.call() ??
                      widget.controllerLoader?.call() ??
                      _loadControllerFromWorkflow() ??
                      _loadControllerFromContracts();
                  setState(() {
                    _controllerFailure = null;
                    _controllerFuture = future;
                  });
                  unawaited(_resolveController(future));
                },
                child: const Text('Retry'),
              ),
            ],
          ),
        ),
      ),
    );
  }

  String _messageFor(Object? error, {required String fallback}) {
    if (error is BrainClientException) return error.message;
    if (error is StateError) return error.message;
    return fallback;
  }

  bool _isMissing(WorkspaceNode node) =>
      node.status == WorkspaceItemStatus.missing;

  bool _isMissingEdge(WorkspaceEdge edge) =>
      edge.status == WorkspaceItemStatus.missing;
}

final class _ExploreAppBar extends StatelessWidget
    implements PreferredSizeWidget {
  const _ExploreAppBar();

  @override
  Widget build(BuildContext context) => AppBar(title: const Text('Explore'));

  @override
  Size get preferredSize => const Size.fromHeight(kToolbarHeight);
}

final class _EmptyWorkspace extends StatelessWidget {
  const _EmptyWorkspace({required this.onSearch});

  final VoidCallback onSearch;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(26),
        child: Column(
          children: [
            Icon(
              Icons.account_tree_outlined,
              size: 48,
              color: Theme.of(context).colorScheme.primary,
            ),
            const SizedBox(height: 10),
            Text('Start with a memory',
                style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 6),
            const Text(
              'Search above or open graph evidence from an answer. Your workspace grows as you explore.',
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 10),
            TextButton(onPressed: onSearch, child: const Text('Search memory')),
          ],
        ),
      ),
    );
  }
}

final class _Notice extends StatelessWidget {
  const _Notice({required this.message, this.icon});

  final String message;
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (icon != null) ...[
            Icon(icon, size: 19),
            const SizedBox(width: 8),
          ],
          Expanded(child: Text(message)),
        ],
      ),
    );
  }
}

String _nodeTitle(GraphNode node) {
  if (node.name?.trim().isNotEmpty == true) return node.name!.trim();
  if (node.summary?.trim().isNotEmpty == true) return node.summary!.trim();
  if (node.content?.trim().isNotEmpty == true) {
    final first = node.content!.split(RegExp(r'[.!?]')).first.trim();
    if (first.isNotEmpty) return first;
  }
  return node.id;
}
