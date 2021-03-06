from typing import List
import matplotlib.pyplot as plt
import matplotlib.pyplot as image
import numpy as np
from sortedcontainers import sorteddict
import prrt.helper as helper
from prrt.grid import WorldGrid
from prrt.primitive import PoseR2S2, PointR2
from prrt.ptg import PTG, APTG
from math import degrees as deg
from prrt.vehicle import ArticulatedVehicle
import time


class Node(object):
    """
    Represents a node in the RRT search tree
    """

    def __init__(self, ptg: PTG, pose: PoseR2S2, parent=None):
        self.pose = pose
        self.parent = parent
        self.ptg = ptg
        self.edges_to_child = []  # type: List[Edge]
        self.id = 0

    def __str__(self):
        return str(self.pose)


class Edge(object):
    """
    An edge connecting two nodes
    """

    def __init__(self, ptg: PTG, k: float, d: float, parent: Node, end_pose: PoseR2S2):
        self.ptg = ptg
        self.k = k
        self.d = d
        self.parent = parent
        self.end_pose = end_pose


class Tree(object):
    """
    Date structure to hold all nodes in RRT
    """

    def __init__(self, init_pose: PoseR2S2):
        root_node = Node(ptg=None, pose=init_pose)
        self.nodes = [root_node]  # type: List[Node]
        self._edges = []  # type: List[Edge]

    def get_aptg_nearest_node(self, to_node: Node, aptg: APTG, mode='TP') -> (PTG, Node, float):
        d_min = float('inf')
        node_min = None
        node_ptg = None
        for node in self.nodes:
            # Only do the the expensive ptg.get_distance when needed
            if abs(node.pose.x - to_node.pose.x) > d_min:
                continue
            if abs(node.pose.y - to_node.pose.y) > d_min:
                continue
            ptg = aptg.ptg_at_phi(node.pose.phi)
            if mode == 'TP':
                d = ptg.get_distance(node.pose, to_node.pose)
            elif mode == 'Metric':
                d = ptg.get_distance_metric(node.pose, to_node.pose)
            if d < d_min:
                d_min = d
                node_min = node
                node_ptg = ptg

        return node_ptg, node_min, d_min

    def insert_node_and_edge(self, parent: Node, child: Node, edge: Edge):
        child.id = len(self.nodes)
        self.nodes.append(child)
        self._edges.append(edge)
        parent.edges_to_child.append(edge)

    def plot_nodes(self, world: WorldGrid, goal: PointR2 = None, goal_dist_tolerance=1.0, file_name=None ):
        import os.path
        file_name_root_eps = './out/tree.eps'
        file_name_root_png = './out/tree.png'
        file_name_png = file_name_root_png
        file_name_eps = file_name_root_eps

        # save the solution in a different file if the file already exist and numerate them
        # TODO: really dirty way of doing it as it will check for all the files, fix this!
        cnt = 0
        while os.path.exists(file_name_png):
            cnt = cnt + 1
            file_name_png = ('{0}{1:04d}.png'.format(file_name_root_png, cnt))

        cnt = 0
        while os.path.exists(file_name_eps):
            cnt = cnt + 1
            file_name_eps = ('{0}{1:04d}.eps'.format(file_name_root_eps, cnt))

        fig, ax = plt.subplots()
        #ax.matshow(world.omap, cmap=plt.cm.gray_r, origin='upper', interpolation='none')
        # instead of showing image first and then the
        map = np.fliplr(world.map_32bit)
        #map = world.map_32bit
        ax.imshow(map, #cmap=plt.cm.gray_r, interpolation='none', #origin='upper',
                  extent=(world.width, 0.0, world.height, 0.0), zorder=-1)
        plt.xlabel('x(m)', fontsize=20)
        plt.ylabel('y(m)', fontsize=20)
        plt.ylim(0, world.height)
        plt.xlim(0, world.width)

        circle = plt.Circle((goal.x, goal.y), goal_dist_tolerance, color='red', fill=False)
        ax.add_artist(circle)
        for node in self.nodes:
            x = node.pose.x #world.x_to_ix(node.pose.x)
            y = node.pose.y #world.y_to_iy(node.pose.y)
            ax.plot(x, y, 'bx')
        if goal is not None:
            ax.plot(goal.x, goal.y, '+r')
            #ax.plot(world.x_to_ix(goal.x), world.y_to_iy(goal.y), '+r')
        # save png
        if file_name_png is None:
            plt.savefig(file_name_png)
        else:
            plt.savefig(file_name_png, format='png', dpi=150, bbox_inches='tight', pad_inches=0.1)
        # save eps
        if file_name_eps is None:
            plt.savefig(file_name_eps)
        else:
            plt.savefig(file_name_eps, format='eps', dpi=150, bbox_inches='tight', pad_inches=0.1)
            # plt.show()


class Planner(object):
    """
    Binds all pieces together and execute the main RRT algorithm
    """

    def __init__(self, config: dict):
        self.aptgs = []  # Type:List[APTG]
        self.world = None  # type: WorldGrid
        self.init_pose = None  # type: PoseR2S2
        self.goal_pose = None  # type: PoseR2S2
        self.tree = None  # type: Tree
        self.config = config
        self.planner_success = False
        self.total_number_of_iterations = 0
        self.total_number_of_nodes = 0
        self.best_path_length = float('inf')
        self.best_distance_to_target = float('inf')
        self.solving_time = float('inf')

    def load_world_map(self, map_file, width: float, height: float):
        self.world = WorldGrid(map_file, width, height)
        self.world.build_obstacle_buffer()

    def load_aptgs(self, files: List[str]):
        for file in files:
            self.aptgs.append(helper.load_object(file))

    def setup(self):
        aptgs_files = self.config['aptg_files']
        self.load_aptgs(aptgs_files)
        map_file = self.config['world_map_file']
        width = self.config['world_width']
        height = self.config['world_height']
        self.load_world_map(map_file, width, height)

    def getResults(self) -> (bool, int, int, float, float, float):
        print("Getting results ")
        return self.planner_success, \
               self.total_number_of_iterations, \
               self.total_number_of_nodes, \
               self.best_path_length, \
               self.best_distance_to_target, \
               self.solving_time

    @staticmethod
    def transform_toTP_obstacles(ptg: PTG, obstacles_ws: List[PointR2], k: int, max_dist: float) -> List[float]:
        # obs_TP = []  # type: List[float]
        # for k in range(len(ptg.cpoints)):
        #     obs_TP.append(ptg.distance_ref)
        # If you just  turned 180deg, end there
        # if len(ptg.cpoints[k]) == 0:
        #     obs_TP[k] = 0.  # Invalid configuration
        #     continue
        # phi = ptg.cpoints[k][-1].theta
        # if abs(phi) >= np.pi * 0.95:
        #     obs_TP[k] = ptg.cpoints[k][-1].d
        obs_TP = [ptg.distance_ref] * len(ptg.cpoints)  # type: List[float]
        for i in range(np.shape(obstacles_ws)[1]):
            if abs(obstacles_ws[0][i]) > max_dist or abs(obstacles_ws[1][i]) > max_dist:
                continue
            obstacle = PointR2(obstacles_ws[0][i], obstacles_ws[1][i])
            collision_cell = ptg.obstacle_grid.cell_by_pos(obstacle)
            if collision_cell is None:
                continue
            # assert collision_cell is not None, 'collision cell is empty!'
            # get min_dist for the current k
            for kd_pair in collision_cell:
                if kd_pair.k == k and kd_pair.d < obs_TP[kd_pair.k]:
                    obs_TP[kd_pair.k] = kd_pair.d
                    break
        return obs_TP

    def solve(self):
        self.setup()  # load aptgs and world map
        init_pose = PoseR2S2.from_dict(self.config['init_pose'])
        goal_pose = PoseR2S2.from_dict(self.config['goal_pose'])
        self.tree = Tree(init_pose)
        goal_dist_tolerance = self.config['goal_dist_tolerance']
        goal_ang_tolerance = self.config['goal_ang_tolerance']
        debug_tree_state = self.config['debug_tree_state']
        debug_tree_state_file = self.config['debug_tree_state_file']
        bias = self.config['rrt_bias']
        obs_R = self.config['obs_R']
        D_max = self.config['D_max']
        solution_found = False
        max_count = self.config['max_count']
        counter = 0
        min_goal_dist_yet = float('inf')
        start_time = time.time()
        while not solution_found and len(self.tree.nodes) < max_count:
            counter += 1
            rand_pose = self.world.get_random_pose(goal_pose, bias)
            candidate_new_nodes = sorteddict.SortedDict()
            rand_node = Node(ptg=None, pose=rand_pose)
            for aptg in self.aptgs:
                ptg, ptg_nearest_node, ptg_d_min = self.tree.get_aptg_nearest_node(rand_node, aptg)
                if ptg_nearest_node is None:
                    print('APTG {0} can\'t find nearest pose to {1}'.format(aptg.name, rand_node))
                    continue
                ptg_nearest_pose = ptg_nearest_node.pose
                rand_pose_rel = rand_pose - ptg_nearest_pose
                d_max = min(D_max, ptg.distance_ref)
                is_exact, k_rand, d_rand = ptg.inverse_WS2TP(rand_pose_rel)
                d_rand *= ptg.distance_ref
                max_dist_for_obstacles = obs_R * ptg.distance_ref
                obstacles_rel = self.world.transform_point_cloud(ptg_nearest_pose, max_dist_for_obstacles)
                obstacles_TP = self.transform_toTP_obstacles(ptg, obstacles_rel, k_rand, max_dist_for_obstacles)
                d_free = obstacles_TP[k_rand]
                d_new = min(d_max, d_rand)
                if debug_tree_state > 0 and counter % debug_tree_state == 0:
                    self.tree.plot_nodes(self.world, ptg_nearest_pose,
                                         '{0}{1:04d}.png'.format(debug_tree_state_file, counter) )
                # Skip if the current ptg and alpha (k_ran) can't reach this point
                if ptg.cpoints[k_rand][-1].d < d_new:
                    #print('Node leads to invalid trajectory. Node Skipped!')
                    continue

                if d_free >= d_new:
                    # get cpoint at d_new
                    cpoint = ptg.get_cpoint_at_d(d_new, k_rand)
                    new_pose_rel = cpoint.pose.copy()
                    new_pose = ptg_nearest_pose + new_pose_rel  # type: PoseR2S2
                    accept_this_node = True
                    goal_dist = new_pose.distance_2d(goal_pose)
                    goal_ang = abs(helper.angle_distance(new_pose.theta, goal_pose.theta))
                    is_acceptable_goal = goal_dist < goal_dist_tolerance and goal_ang < goal_ang_tolerance
                    new_nearest_node = None  # type: Node
                    if not is_acceptable_goal:
                        new_node = Node(ptg, new_pose)
                        new_nearest_ptg, new_nearest_node, new_nearest_dist = self.tree.get_aptg_nearest_node(new_node,
                                                                                                              aptg)
                        if new_nearest_node is not None:
                            new_nearest_ang = abs(helper.angle_distance(new_pose.theta, new_nearest_node.pose.theta))
                            accept_this_node = new_nearest_dist >= 0.1 or new_nearest_ang >= 0.35
                            # ToDo: make 0.1 and 0.35 configurable parameters
                    if not accept_this_node:
                        continue
                    new_edge = Edge(ptg, k_rand, d_new, ptg_nearest_node, new_pose)
                    candidate_new_nodes.update({d_new: new_edge})
                    #print('Candidate node found')
                else:  # path is not free
                    #print('Obstacle ahead!')
                    # do nothing for now
                    pass
            if len(candidate_new_nodes) > 0:
                best_edge = candidate_new_nodes.peekitem(-1)[1]  # type : Edge
                new_state_node = Node(best_edge.ptg, best_edge.end_pose, best_edge.parent)
                self.tree.insert_node_and_edge(best_edge.parent, new_state_node, best_edge)
                #print('new node added to tree from ptg {0}'.format(best_edge.ptg.name))
                goal_dist = best_edge.end_pose.distance_2d(goal_pose)
                print("New note : ", new_state_node.pose)
                print("Goal distance of the current node : ", goal_dist)
                goal_ang = abs(helper.angle_distance(best_edge.end_pose.theta, goal_pose.theta))
                is_acceptable_goal = goal_dist < goal_dist_tolerance and goal_ang < goal_ang_tolerance
                min_goal_dist_yet = min(goal_dist, min_goal_dist_yet)
                print("Best Goal distance : ", min_goal_dist_yet)
                if is_acceptable_goal:
                    print('goal reached!')
                    break
                    # To do: continue running to refine solution
                print("Counter = ",counter, "   Number of nodes :", len(self.tree.nodes))
        self.solving_time = time.time() - start_time
        print('Done in {0:.2f} seconds'.format(time.time() - start_time))
        #self.solving_time = time.time() - start_time
        print('Minimum distance to goal reached is {0}'.format(min_goal_dist_yet))
        if not is_acceptable_goal:
            print('Solution not found within iteration limit')
            self.planner_success = False
            self.total_number_of_iterations = counter
            self.total_number_of_nodes = len(self.tree.nodes)
            self.best_path_length = 0.0 #Todo : add calculation!
            self.best_distance_to_target = min_goal_dist_yet

            # dump results
            if self.config['csv_out_file'] != '':
                self.solution_to_csv(self.config['csv_out_file'])
            if self.config['plot_tree_file'] != '':
                self.tree.plot_nodes(self.world, goal_pose, self.config['goal_dist_tolerance'], self.config['plot_tree_file'])
            #if self.config['plot_solution'] != '':
            #   self.trace_solution(self.aptgs[0].vehicle, goal_pose, self.config['plot_solution'])
            return
        # set parameters to get results
        self.planner_success = True
        self.total_number_of_iterations = counter
        self.total_number_of_nodes = len(self.tree.nodes)
        self.best_path_length = 0.0  # Todo : add calculation!
        self.best_distance_to_target = min_goal_dist_yet
        # dump results
        if self.config['csv_out_file'] != '':
            self.solution_to_csv(self.config['csv_out_file'])
        if self.config['plot_tree_file'] != '':
            self.tree.plot_nodes(self.world, goal_pose, self.config['goal_dist_tolerance'], self.config['plot_tree_file'])
        if self.config['plot_solution'] != '':
            self.trace_solution(self.aptgs[0].vehicle, goal_pose, self.config['plot_solution'])

    def trace_solution(self, vehicle: ArticulatedVehicle, goal: PoseR2S2 = None, file_name='frame'):
        child_node = self.tree.nodes[-1]
        trajectory = []  # type #: List[Edge]
        while True:
            parent_node = child_node.parent
            if parent_node is None:
                break
            trajectory.append(self.get_trajectory_edge(parent_node, child_node))
            child_node = parent_node
        fig, ax = plt.subplots()
        plt.autoscale(tight=True)

        frame = 0
        #ax.matshow(self.world.omap, cmap=plt.cm.gray_r, origin='lower')
        # instead of showing image first and then the
        map = np.fliplr(self.world.map_32bit)
        #map = self.world.map_32bit
        ax.imshow(map, #cmap=plt.cm.gray_r,# origin='upper', interpolation='none',
                  extent=(self.world.width, 0.0, self.world.height, 0.0), zorder=-1)
        plt.xlabel('x(m)', fontsize=20)
        plt.ylabel('y(m)', fontsize=20)
        plt.ylim(0, self.world.height)
        plt.xlim(0, self.world.width)
        circle = plt.Circle((goal.x, goal.y), self.config['goal_dist_tolerance'], color='red', fill=False)
        ax.add_artist(circle)

        for i in range(len(trajectory) - 1, -1, -1):
            # plot the vehicle
            edge = trajectory[i]
            start_pose = edge.parent.pose.copy()
            color = 'b'
            for d in np.arange(0., edge.d, 0.2):
                c_point = edge.ptg.get_cpoint_at_d(d, edge.k)
                current_pose = start_pose + c_point.pose
                vehicle.phi = c_point.phi
                #ATTENTION: this may not work, I have commented the function
                #vehicle.plot(ax, current_pose, self.world, color)
                vehicle.plot(ax, current_pose, color)

                title = r'$x={0:.1f},y={1:.1f},\theta={2:+.1f}^\circ,\phi={3:+.1f}^\circ, v={4:+.1f}, \omega={5:+.1f}, \alpha={6:+.1f}^\circ$'.format(
                    current_pose.x,
                    current_pose.y,
                    deg(current_pose.theta),
                    deg(current_pose.phi),
                    c_point.v,
                    c_point.w,
                    deg(c_point.alpha))
                #fig.suptitle(title, x=0.5, y=1.0)
                if goal is not None:
                    #ax.plot(self.world.x_to_ix(goal.x), self.world.y_to_iy(goal.y), '+r')
                    ax.plot(goal.x, goal.y, '+r')

                print('Saving frame {0}'.format(frame))
                plt.savefig('{0}{1:04d}.png'.format(file_name, frame), dpi=200) #, bbox_inches='tight', pad_inches=0.2)
                # clear the figure for next drawing
                ax.lines = []
                frame += 1

    def solution_to_csv(self, file_name='solution.csv'):
        import csv
        import os.path
        child_node = self.tree.nodes[-1]
        trajectory = []  # type #: List[Edge]
        solution_length = 0.0
        file_name_root = file_name

        # save the solution in a different file if the file already exist and numerate them
        # TODO: really dirty way of doing it as it will check for all the files, fix this!
        cnt = 0
        while os.path.exists(file_name):
            cnt = cnt + 1
            file_name = ('{0}{1:04d}.csv'.format(file_name_root, cnt))

        while True:
            parent_node = child_node.parent
            if parent_node is None:
                break
            trajectory.append(self.get_trajectory_edge(parent_node, child_node))
            solution_length = solution_length + parent_node.pose.distance_2d(child_node.pose)
            child_node = parent_node
        self.best_path_length = solution_length
        with open(file_name, 'w', newline='') as csvfile:
            csv_writer = csv.writer(csvfile, delimiter=',')
            for i in range(len(trajectory) - 1, -1, -1):
                edge = trajectory[i]
                start_pose = edge.parent.pose.copy()
                for d in np.arange(0., edge.d, 0.2):
                    c_point = edge.ptg.get_cpoint_at_d(d, edge.k)
                    current_pose = start_pose + c_point.pose
                    row = [current_pose.x, current_pose.y, current_pose.theta, current_pose.phi, c_point.v,
                           c_point.w]
                    csv_writer.writerow([edge.ptg.name, edge.parent.id] + ['{0:+.4f}'.format(x) for x in row])

        print('Dumping solution to csv file done')

    @staticmethod
    def get_trajectory_edge(parent: Node, child: Node) -> Edge:
        for edge in parent.edges_to_child:
            if edge.end_pose == child.pose:
                return edge

    def __del__(self):
        del self.aptgs  # Type:List[APTG]
        del self.world   # type: WorldGrid
        del self.init_pose   # type: PoseR2S2
        del self.goal_pose   # type: PoseR2S2
        del self.tree   # type: Tree
        del self.config
        del self.planner_success
        del self.total_number_of_iterations
        del self.total_number_of_nodes
        del self.best_path_length
        del self.best_distance_to_target
        del self.solving_time