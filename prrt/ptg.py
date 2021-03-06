from abc import ABCMeta, abstractmethod
from prrt.vehicle import ArticulatedVehicle
from prrt.primitive import PoseR2S2, CPoint, PointR2
import numpy as np
import prrt.helper as helper
from typing import List, Type
from prrt.grid import ObstacleGrid, CPointsGrid
from math import tan, sqrt, radians as rad, degrees as deg, pi as PI


class PTG(metaclass=ABCMeta):
    """
    Base class for parametrized trajectory generators.
    """

    def __init__(self, vehicle: ArticulatedVehicle, config: dict):
        # check the provided config file for details on the variables initialized below
        self.vehicle = vehicle
        self.K = config['K']  # type: int
        self.dt = config['dt']  # type: float
        self.alpha_max = rad(config['alpha_max'])  # type: float
        self.alpha_resolution = rad(config['alpha_resolution'])  # type: float
        self.n_max = config['n_max']  # type: int
        self.d_max = config['grid_size']  # type: float
        self.cpoints = []  # type: List[List[CPoint]]
        self.idx_to_alpha = []
        self.min_dist_between_cpoints = config['min_dist_between_cpoints']  # type: float
        self.k_theta = config['k_theta']  # type: float
        self.distance_ref = config['grid_size']  # type: float
        self.obstacle_grid = ObstacleGrid(3 * config['grid_size'], 3 * config['grid_resolution'])
        self.cpoints_grid = CPointsGrid(config['grid_size'], config['grid_resolution'])
        self.name = config['name']
        # initial phi is meant to be added by the caller (eg. APTG). Assume it 0 if not available
        self.init_phi = rad(config['init_phi'] if config.get('init_phi') is not None else 0.)

    @abstractmethod
    def build_cpoints(self):
        """
        Builds a distance map for the given PTG, map grid_size, grid_resolution and vehicle
        """
        pass

    def build_obstacle_grid(self):
        """
        For each cpoint in cpoints at a given alpha:
            1- place the vehicle at cpoint.pose
            2- See which cells it collides with
            3- Update the cells with alpha and d values
        """
        from prrt.primitive import get_bounding_box, polygon_contains_point as polygon_contains_point
        assert len(self.cpoints) > 0, 'cpoints don\'t exist!'
        for k in range(len(self.idx_to_alpha)):
            cpoints_at_k = self.cpoints[k]
            for cpoint in cpoints_at_k:
                shape_tractor = self.vehicle.get_tractor_vertices_at_pose(cpoint.pose)
                shape_trailer = self.vehicle.get_trailer_vertices_at_pose(cpoint.pose)
                shapes = [shape_tractor, shape_trailer]
                for shape in shapes:
                    shape_bb = get_bounding_box(shape)
                    x_idx_min = max(0, self.obstacle_grid.x_to_ix(shape_bb[0].x))
                    y_idx_min = max(0, self.obstacle_grid.y_to_iy(shape_bb[0].y))
                    x_idx_max = min(self.obstacle_grid.cell_count_x - 1, self.obstacle_grid.x_to_ix(shape_bb[1].x))
                    y_idx_max = min(self.obstacle_grid.cell_count_y - 1, self.obstacle_grid.y_to_iy(shape_bb[1].y))
                    for x_idx in range(x_idx_min - 1, x_idx_max + 1):
                        cell = PointR2()
                        cell.x = self.obstacle_grid.idx_to_x(x_idx)
                        for y_idx in range(y_idx_min - 1, y_idx_max + 1):
                            cell.y = self.obstacle_grid.idx_to_y(y_idx)
                            if polygon_contains_point(shape, cell, shape_bb):
                                self.obstacle_grid.update_cell(x_idx, y_idx, k, cpoint.d)
                                self.obstacle_grid.update_cell(x_idx - 1, y_idx, k, cpoint.d)
                                self.obstacle_grid.update_cell(x_idx, y_idx - 1, k, cpoint.d)
                                self.obstacle_grid.update_cell(x_idx - 1, y_idx - 1, k, cpoint.d)
        print('Completed building obstacle grid for {0}'.format(self.name))

    def build(self):
        self.build_cpoints()
        self.build_obstacle_grid()
        self.build_cpoints_grid()

    def build_cpoints_grid(self):
        '''
        Build cpoints_grid by looping through each cpoints for each trajectory.
            each cpoint is mapped to a cell in the cpoints_grid and updated with
            the cpoint alpha index and point index.
            Note: For circular PTG an explicit equation is available nad the grid
                    is not used
        '''
        assert len(self.cpoints) > 0, 'call build_cpoints before'
        print('Starting building cpoints grid for {0}'.format(self.name))
        k = 0  # k is the index of alpha
        for cpoints_at_k in self.cpoints:
            n = 0
            for cpoint in cpoints_at_k:
                ix = self.cpoints_grid.x_to_ix(cpoint.x)
                iy = self.cpoints_grid.y_to_iy(cpoint.y)
                self.cpoints_grid.update_cell(ix, iy, k, n)
                n += 1
            k += 1
        print('Completed building cpoints grid for {0}'.format(self.name))

    def get_distance(self, from_pose: PoseR2S2, to_pose: PoseR2S2) -> float:
        to_at_from = to_pose - from_pose
        is_exact, k, d = self.inverse_WS2TP(to_at_from)
        if is_exact:
            return d * self.distance_ref
        else:
            return float('inf')

    def get_distance_metric(self, from_pose: PoseR2S2, to_pose: PoseR2S2) -> float:
        delta_pose = to_pose.diff(from_pose)
        return sqrt(delta_pose.x ** 2 + delta_pose.y ** 2 + delta_pose.theta ** 2)

    def alpha2idx(self, alpha: float) -> int:
        alpha = helper.wrap_to_npi_pi(alpha)
        if abs(alpha) > self.alpha_max:
            alpha = np.sign(alpha) * self.alpha_max
        delta = alpha + self.alpha_max
        return int(np.rint(delta / self.alpha_resolution))

    def inverse_WS2TP(self, p: PoseR2S2, tolerance=0.1) -> (bool, int, float):
        k_min = 100000
        k_max = 0
        n_min = 100000
        n_max = 0
        at_least_once = False
        ix = self.cpoints_grid.x_to_ix(p.x)
        iy = self.cpoints_grid.y_to_iy(p.y)
        for i in [ix - 1, ix, ix + 1]:
            for j in [iy - 1, iy, iy + 1]:
                cell = self.cpoints_grid.cell_by_idx(ix, iy)
                if cell is not None:
                    cell_k_min, cell_n_min, cell_k_max, cell_n_max = cell
                    k_min = min(k_min, cell_k_min)
                    n_min = min(n_min, cell_n_min)
                    k_max = max(k_max, cell_k_max)
                    n_max = max(n_max, cell_n_max)
                    at_least_once = True

        k_best = -1
        d_best = -1.
        least_dist_square = float('inf')
        if at_least_once:
            for k in range(k_min, k_max + 1):
                for n in range(n_min, min(n_max + 1, len(self.cpoints[k]))):
                    cpoint = self.cpoints[k][n]
                    dist_square = (p.x - cpoint.x) ** 2 + (p.y - cpoint.y) ** 2
                    if dist_square < least_dist_square:
                        least_dist_square = dist_square
                        k_best = k
                        d_best = cpoint.d
            d = sqrt(d_best) / self.distance_ref
            return True, k_best, d  # Exact cpoint, at alpha index = k, with distance d

        # Point not within grid, extrapolate trajectories to reach the point
        for cpoints_at_k in self.cpoints:
            cpoint = cpoints_at_k[-1]  # get last point in trajectory
            dist_square = cpoint.d ** 2 + (p.x - cpoint.x) ** 2 + (p.y - cpoint.y) ** 2
            if dist_square < least_dist_square:
                least_dist_square = dist_square
                k_best = self.alpha2idx(cpoint.alpha)
                d_best = dist_square
        d = sqrt(d_best) / self.distance_ref
        return False, k_best, d  # Exact cpoint, at alpha index = k, with distance d

    def get_cpoint_at_d(self, d: float, k: int) -> CPoint:
        assert k < len(self.cpoints), 'k value exceeds bound'''
        for cpoint in self.cpoints[k]:
            if cpoint.d >= d:
                return cpoint

    def plot_trajectories(self, axes):
        for cpoints_at_k in self.cpoints:
            x = [cpoint.pose.x for cpoint in cpoints_at_k]
            y = [cpoint.pose.y for cpoint in cpoints_at_k]
            axes.plot(x, y, label=r'$\alpha = {0:.1f}^\circ$'.format(deg(cpoints_at_k[0].alpha)))
            axes.legend(loc='upper left', shadow=True)


class CPTG(PTG):
    """
    Circular path PTG. Paths are generated by selecting a fixed
    alpha
    """

    def build_cpoints(self):
        """
        Builds a list of cpoint trajectories for each alpha value (steering angle)
        References:
            1- Blanco, Jose-Luis, Javier González, and Juan-Antonio Fernández-Madrigal. "Extending obstacle avoidance methods through multiple parameter-space transformations." Autonomous Robots 24.1 (2008): 29-48.
            2- Lamiraux, Florent, Sepanta Sekhavat, and J-P. Laumond. "Motion planning and control for Hilare pulling a trailer." IEEE Transactions on Robotics and Automation 15.4 (1999): 640-652.
        """
        r = self.vehicle.tractor_l  # see ref 1
        # generate trajectories for each steering angle 
        for alpha in np.arange(-self.alpha_max, self.alpha_max + self.alpha_resolution,
                               self.alpha_resolution):
            n = 0
            v = self.K * self.vehicle.v_max
            pose = PoseR2S2(0., 0., 0., self.init_phi)
            dist = 0.  # tp_space distance
            last_pose = pose.copy()
            w = v / self.vehicle.tractor_l * tan(alpha)  # rotational velocity
            rotation = 0.  # same as pose.theta but defined over the range [0: 2PI)
            self.idx_to_alpha.append(alpha)
            cpoints_at_alpha = [CPoint(pose, 0., v, w, alpha)]  # type: List[CPoint]
            while abs(rotation) < 1.95 * PI and dist < self.d_max and n < self.n_max and abs(
                    pose.phi) <= self.vehicle.phi_max:
                pose = self.vehicle.execute_motion(pose, v, w, self.dt)
                rotation += w * self.dt
                v_tp_space = sqrt(v * v + (w * r) * (w * r))
                dist += v_tp_space * self.dt
                delta_pose = pose - last_pose
                dist1 = delta_pose.norm
                dist2 = abs(delta_pose.theta) * self.k_theta
                dist_max = max(dist1, dist2)
                if dist_max > self.min_dist_between_cpoints:
                    cpoints_at_alpha.append(CPoint(pose.copy(), dist, v, w, alpha, n))
                    last_pose.copy_from(pose)
                    n += 1
            self.cpoints.append(cpoints_at_alpha)
        print('Completed building cpoints for {0}'.format(self.name))

    def inverse_WS2TP(self, p: PoseR2S2, tolerance=0.1) -> (bool, int, float):
        is_exact = True
        turn_radius = self.vehicle.tractor_l
        if p.y != 0:
            R = (p.x * p.x + p.y * p.y) / (2 * p.y)
            Rmin = abs(self.vehicle.v_max / self.vehicle.w_max)
            if self.K > 0:
                if p.y > 0:
                    theta = np.arctan2(p.x, abs(R) - p.y)
                else:
                    theta = np.arctan2(p.x, p.y + abs(R))
            else:
                if p.y > 0:
                    theta = np.arctan2(-p.x, abs(R) - p.y)
                else:
                    theta = np.arctan2(-p.x, p.y + abs(R))
                    # Arc length must be positive [0,2*pi]
            theta = helper.wrap_to_0_2pi(theta)
            # Distance through arc:
            d = theta * (abs(R) + turn_radius)
            if abs(R) < Rmin:
                is_exact = False
                R = Rmin * np.sign(R)
            a = np.pi * self.vehicle.v_max / (self.vehicle.w_max * R)
            ik = self.alpha2idx(a)
            if abs(a) > self.alpha_max + self.alpha_resolution:
                is_exact = False
        else:
            if np.sign(p.x) == np.sign(self.K):
                ik = self.alpha2idx(0)
                d = p.x
                is_exact = True
            else:
                ik = self.alpha2idx(np.pi)
                d = 1e+3
                is_exact = False
        # Normalize:
        d /= self.distance_ref
        assert ik >= 0, 'k index must not be negative'
        assert ik < len(self.cpoints), 'ik exceeds limit'
        return is_exact, ik, d


class AlphaA_PTG(PTG):
    """
    Alpha-A PTG
    Ref: Blanco, Jose-Luis, Javier González, and Juan-Antonio Fernández-Madrigal. "Extending obstacle avoidance methods through multiple parameter-space transformations." Autonomous Robots 24.1 (2008): 29-48.
    """

    def build_cpoints(self):
        from math import exp
        r = self.vehicle.tractor_l  # see ref 1
        # generate trajectories for each steering angle
        for alpha in np.arange(-self.alpha_max, self.alpha_max + self.alpha_resolution,
                               self.alpha_resolution):
            n = 0
            v = self.K * self.vehicle.v_max
            pose = PoseR2S2(0., 0., 0., self.init_phi)
            dist = 0.  # tp_space distance
            last_pose = pose.copy()
            w = v / self.vehicle.tractor_l * tan(alpha)  # rotational velocity
            rotation = 0.  # same as pose.theta but defined over the range [0: 2PI)
            self.idx_to_alpha.append(alpha)
            cpoints_at_alpha = [CPoint(pose, 0., v, w, alpha)]  # type: List[CPoint]
            while abs(rotation) < 1.95 * PI and dist < self.d_max and n < self.n_max and abs(
                    pose.phi) <= self.vehicle.phi_max:

                # calculate control parameters
                delta = helper.wrap_to_npi_pi(alpha - pose.theta)
                v = self.K * self.vehicle.v_max * exp(-(delta / 1.) ** 2)
                w = self.K * self.vehicle.w_max * (-0.5 + (1 / (1 + exp(-delta / 1.))))
                pose = self.vehicle.execute_motion(pose, v, w, self.dt)
                rotation += w * self.dt
                v_tp_space = sqrt(v * v + (w * r) * (w * r))
                dist += v_tp_space * self.dt
                delta_pose = pose - last_pose
                dist1 = delta_pose.norm
                dist2 = abs(delta_pose.theta) * self.k_theta
                dist_max = max(dist1, dist2)
                if dist_max > self.min_dist_between_cpoints:
                    cpoints_at_alpha.append(CPoint(pose.copy(), dist, v, w, alpha, n))
                    last_pose.copy_from(pose)
                    n += 1
            self.cpoints.append(cpoints_at_alpha)
        print('Completed building cpoints for {0}'.format(self.name))


class APTG(object):
    '''
        Articulated PTG. This class wraps a vector of PTGs that differ only
         by the initial articulation angle.
    '''

    def __init__(self, vehicle: ArticulatedVehicle, config: dict):
        self.ptgs = []  # type: List[PTG]
        self.name = config['name']
        self.ptg_module_name = config['ptg_module']
        self.ptg_class_name = config['ptg_class']
        self.alpha_resolution = rad(config['alpha_resolution'])
        self.phi_resolution = rad(config['phi_resolution'])
        self.config = config
        module = __import__(self.ptg_module_name, fromlist=[self.ptg_class_name])
        self.ptg_class = getattr(module, self.ptg_class_name)  # type: Type[PTG]
        self.vehicle = vehicle

    def build(self, skip_collision_calc=False):
        '''
        build the PTG vector, by sampling phi at the specified resolution
        Warning: Takes a while to complete, around 1 hour on the default configurations
        To speed up testing of collision unrelated feature set skip_collision_calc to True
        '''
        phi_max = self.vehicle.phi_max
        for phi in np.arange(-phi_max, phi_max + self.phi_resolution,
                             self.phi_resolution):
            self.config['init_phi'] = min(deg(phi), 30.)
            self.config['name'] = '{0}_init_phi = {1:0.1f}'.format(self.name, deg(phi))
            ptg = self.ptg_class(self.vehicle, self.config)
            if skip_collision_calc:
                ptg.build_cpoints()
            else:
                ptg.build()
            self.ptgs.append(ptg)

    def dump(self, file_name):
        '''
        Instead of rebuilding the PTGs vector each time, a dump is saved
        that can later be read in seconds. The dump is based on python pickle package.
        The dump can be used as long as the vehicle and the APTG configuration
        have not changed. Warning: No checks is done in code to verify this.
        '''
        helper.save_object(self, file_name)

    def ptg_at_phi(self, phi: float) -> PTG:
        # get the ptg with the nearest phi_init
        delta = phi - (-self.vehicle.phi_max)
        idx = int(np.rint(delta / self.phi_resolution))
        assert idx <= len(self.ptgs), 'Articulation angel (phi) out of range!'
        return self.ptgs[idx]
