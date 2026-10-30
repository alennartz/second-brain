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
import '../widgets/memory_labels.dart';
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
  int _searchGeneration = 0;
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
    if (oldWidget.brainId != widget.brainId ||
        oldWidget.gateway != widget.gateway ||
        oldWidget.workflow != widget.workflow) {
      _searchGeneration++;
      _searchResult = null;
      _searchFailure = null;
      _searching = false;
      _refreshing = false;
      _query = '';
      _searchController.clear();
    }
    if (widget.controller != null) {
      if (!identical(widget.controller, _controller)) {
        _controllerFuture = null;
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
    final sourceChanged =
        oldWidget.controllerFuture != widget.controllerFuture ||
            oldWidget.loadController != widget.loadController ||
            oldWidget.controllerLoader != widget.controllerLoader ||
            oldWidget.workspaces != widget.workspaces ||
            oldWidget.workspaceRepository != widget.workspaceRepository;
    final directControllerRemoved = oldWidget.controller != widget.controller;
    if (profileChanged || sourceChanged || directControllerRemoved) {
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
    final selected = state.nodes.cast<WorkspaceNode?>().firstWhere(
          (item) => item?.node.id == state.selectedNodeId,
          orElse: () => null,
        );
    final raw = _searchResult?.unprocessed ?? const <IntakeChunk>[];
    return SafeArea(
      top: false,
      child: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
            child: _searchField(context),
          ),
          if (_searching || _refreshing) const LinearProgressIndicator(),
          if (_searchFailure != null || _notice != null)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
              child: _Notice(
                message: _searchFailure == null
                    ? _notice!
                    : _messageFor(_searchFailure,
                        fallback: 'Search failed. Try again when connected.'),
              ),
            ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: Row(
              children: [
                Expanded(
                  child: Text(
                    '${state.nodes.where((item) => item.expanded).length} memories · ${state.edges.length} connections',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                ),
                IconButton(
                  tooltip: 'Refresh',
                  onPressed: _refreshing
                      ? null
                      : () => unawaited(_refresh(controller)),
                  icon: const Icon(Icons.refresh),
                ),
                PopupMenuButton<String>(
                  tooltip: 'Workspace options',
                  onSelected: (action) {
                    if (action == 'deleted') _clearDeleted(controller);
                    if (action == 'clear') {
                      unawaited(_clearWorkspace(controller));
                    }
                  },
                  itemBuilder: (_) => [
                    PopupMenuItem(
                      value: 'deleted',
                      enabled: state.nodes.any(_isMissing) ||
                          state.edges.any(_isMissingEdge),
                      child: const Text('Clear deleted'),
                    ),
                    PopupMenuItem(
                      value: 'clear',
                      enabled: state.nodes.isNotEmpty || state.edges.isNotEmpty,
                      child: const Text('Clear workspace'),
                    ),
                  ],
                ),
              ],
            ),
          ),
          Expanded(
            child: state.nodes.isEmpty && state.edges.isEmpty
                ? Center(
                    child: SingleChildScrollView(
                        child: _EmptyWorkspace(onSearch: _focusSearch)))
                : LayoutBuilder(
                    builder: (_, constraints) => GraphCanvas(
                      height: constraints.maxHeight,
                      state: state,
                      focusRevision: _searchGeneration,
                      onSelectNode: (id) =>
                          unawaited(_expandNode(controller, id)),
                      onSelectEdge: (id) =>
                          unawaited(_followEdge(controller, id)),
                    ),
                  ),
          ),
          if (selected != null)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      memoryTitle(selected.node),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.titleSmall,
                    ),
                  ),
                  TextButton.icon(
                    onPressed: () =>
                        unawaited(_showDetails(controller, selected.node.id)),
                    icon: const Icon(Icons.subject),
                    label: const Text('Details'),
                  ),
                ],
              ),
            ),
          if (raw.isNotEmpty)
            TextButton(
              onPressed: () => _showUnprocessed(raw),
              child: Text('Unprocessed evidence (${raw.length})'),
            ),
        ],
      ),
    );
  }

  Widget _searchField(BuildContext context) {
    return TextField(
      controller: _searchController,
      focusNode: _searchFocus,
      textInputAction: TextInputAction.search,
      onChanged: (value) => setState(() => _query = value),
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

  void _showUnprocessed(List<IntakeChunk> chunks) {
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (context) => SafeArea(
        child: SizedBox(
          height: MediaQuery.sizeOf(context).height * .65,
          child: ListView(
            padding: const EdgeInsets.all(20),
            children: [
              Text('Unprocessed evidence',
                  style: Theme.of(context).textTheme.titleLarge),
              const SizedBox(height: 12),
              ...chunks.map((chunk) => Card(
                    child: Padding(
                      padding: const EdgeInsets.all(16),
                      child: Text(chunk.content),
                    ),
                  )),
            ],
          ),
        ),
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
    return ExploreWorkspaceControllerImpl.load(
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
      if (!mounted || !identical(future, _controllerFuture)) return;
      setState(() => _controller = controller);
      try {
        await controller.refreshCompleted;
      } on Object {
        // Cached graph data remains available when refresh fails.
      }
      if (!mounted || !identical(controller, _controller)) return;
      setState(() {});
    } on Object catch (error) {
      if (!mounted) return;
      if (!identical(future, _controllerFuture)) return;
      setState(() => _controllerFailure = error);
    }
  }

  Future<void> _search() async {
    final query = _query.trim();
    if (query.isEmpty) return;
    final generation = ++_searchGeneration;
    FocusManager.instance.primaryFocus?.unfocus();
    final gateway = widget.gateway;
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
      if (!mounted || generation != _searchGeneration) return;
      final controller = _controller;
      if (controller == null) return;
      if (result.nodes.isNotEmpty) {
        await controller.addSearchMatches(result.nodes);
      }
      if (!mounted ||
          generation != _searchGeneration ||
          !identical(controller, _controller)) return;
      setState(() {
        _searchResult = result;
        _searching = false;
        _notice = result.nodes.isEmpty
            ? 'No graph memories matched this search.'
            : null;
      });
      if (result.nodes.isNotEmpty) {
        try {
          await controller.refreshCompleted;
        } on Object {
          // This search still needs its own connection refresh.
        }
        if (!mounted ||
            generation != _searchGeneration ||
            !identical(controller, _controller)) return;
        await _refresh(controller);
      }
    } on Object catch (error) {
      if (!mounted) return;
      if (generation != _searchGeneration) return;
      setState(() {
        _searchFailure = error;
        _searching = false;
        _searchResult = null;
      });
    }
  }

  Future<void> _expandNode(
    ExploreWorkspaceController controller,
    String id,
  ) async {
    controller.selectNode(id);
    setState(() {});
    try {
      await controller.openNode(id);
      if (mounted && identical(controller, _controller)) setState(() {});
    } on Object catch (error) {
      if (mounted && identical(controller, _controller)) {
        setState(() => _notice = _messageFor(error,
            fallback:
                'Could not load this memory. Cached data is still available.'));
      }
    }
  }

  Future<void> _showDetails(
    ExploreWorkspaceController controller,
    String id,
  ) async {
    final callback =
        widget.onOpenDetail ?? widget.onOpenNode ?? widget.onNodeSelected;
    if (callback != null) {
      callback(id);
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
      if (!mounted || !identical(controller, _controller)) return;
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
    _searchGeneration++;
    setState(() {
      _searching = false;
      _searchResult = null;
      _searchFailure = null;
    });
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
    if (error is HttpStatusException) {
      if (error.statusCode == 401 || error.statusCode == 403) {
        return 'Check this brain’s access credentials.';
      }
      if (error.statusCode == 404) return 'This memory is no longer available.';
    }
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
  const _Notice({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: Theme.of(context).colorScheme.surfaceContainerHighest,
          borderRadius: BorderRadius.circular(12),
        ),
        child: Text(message),
      );
}
