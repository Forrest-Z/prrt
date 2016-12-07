from abc import ABCMeta, abstractmethod
from prrt.vehicle import Vehicle, ArticulatedVehicle
from prrt.primitive import PoseR2S1, CPoint, PointR2
import numpy as np
import matplotlib.pyplot as plt
import prrt.helper as helper
from typing import List
from prrt.grid import ObstacleGrid, CPointsGrid
import math


class PTG(metaclass=ABCMeta):
    """
    Base class for parametrized trajectory generators.
    """

    def __init__(self, size: float, vehicle: Vehicle, resolution: float):
        """

        :type size: float > 0 (in meters). Map will extend from (-size,-size) to (size, size)
        :type vehicle: Vehicle. provides car_vertices and kinematics of the vehicle
        :type resolution: float > 0 (in meters). Resolution of map grid
        """
        self._vehicle = vehicle
        self._delta_t = 0.0005
        self._alpha_resolution = np.deg2rad(3.)
        self._t_max = 100.0
        self._n_max = 10000
        self._d_max = size
        self.c_points = []  # type: List[List[CPoint]]
        self.idx_to_alpha = []
        self._turning_radius_ref = 0.1
        self.distance_ref = size
        self.obstacle_grid = ObstacleGrid(size, resolution)
        self._c_points_grid = CPointsGrid(size, resolution)
        self.name = 'PTG'

    @abstractmethod
    def build_cpoints(self):
        """
        Builds a distance map for the given PTG, map size, resolution and vehicle
        """
        pass

    @abstractmethod
    def get_distance(self, from_pose: PoseR2S1, to_pose: PoseR2S1) -> float:
        delta_pose = to_pose - from_pose
        return delta_pose.norm

    def alpha2idx(self, alpha: float) -> int:
        alpha = helper.wrap_to_npi_pi(alpha)
        if abs(alpha) > self._vehicle.alpha_max:
            alpha = np.sign(alpha) * self._vehicle.alpha_max
        delta = alpha + self._vehicle.alpha_max
        return int(np.rint(delta / self._alpha_resolution))

    @abstractmethod
    def inverse_WS2TP(self, p: PoseR2S1, tolerance=0.1) -> (bool, int, float):
        pass

    def get_cpoint_at_d(self, d: float, k: int) -> CPoint:
        assert k < len(self.c_points), 'k value exceeds bound'''
        for c_point in self.c_points[k]:
            if c_point.d >= d:
                return c_point


class CPTG(PTG):
    """
    Circular path PTG. Paths are generated by selecting a fixed
    alpha
    """

    def __init__(self, size: float, vehicle: Vehicle, resolution: float, K: int):
        self._K = K
        super(CPTG, self).__init__(size, vehicle, resolution)

    def build_cpoints(self):
        """
        Builds a distance map for the given PTG, map size, resolution and vehicle
        """
        k_theta = 1.
        min_dist = 0.015
        turning_radius = 0.1
        print('Starting building cpoints for {0}'.format(self.name))
        for alpha in np.arange(-self._vehicle.alpha_max, self._vehicle.alpha_max + self._alpha_resolution,
                               self._alpha_resolution):
            t = 0.
            n = 0
            v = self._K * self._vehicle.v_max
            self._vehicle.pose = PoseR2S1(0., 0., 0.)
            self._vehicle.phi = 0.
            dist = 0.
            last_pose = PoseR2S1(0, 0, 0)
            w = (alpha / np.pi) * self._vehicle.w_max
            rotation = 0.  # same as pose.theta but defined over the range [0: 2PI)
            self.idx_to_alpha.append(alpha)
            points = []  # type: List[CPoint]
            while abs(rotation) < 1.95 * np.pi and t < self._t_max and dist < self._d_max and n < self._n_max:
                pose = self._vehicle.execute_motion(self._K, w, self._delta_t)
                rotation += w * self._delta_t
                v_tp_space = np.sqrt(v * v + (w * turning_radius) * (w * turning_radius))
                dist += v_tp_space * self._delta_t
                delta_pose = pose - last_pose
                dist1 = delta_pose.norm
                dist2 = abs(delta_pose.theta) * k_theta
                dist_max = max(dist1, dist2)
                t += self._delta_t
                if dist_max > min_dist:
                    points.append(CPoint(pose.copy(), t, dist, v, w, self._vehicle.phi))
                    last_pose.copy_from(pose)
                    n += 1
            self.c_points.append(points)
        print('Completed building cpoints for {0}'.format(self.name))

    def build_cpoints_grid(self):
        assert len(self.c_points) > 0, 'call build_cpoints before'
        print('Starting building cpoints grid for {0}'.format(self.name))
        k = 0
        for c_points_at_k in self.c_points:
            n = 0
            for c_point in c_points_at_k:
                ix = self._c_points_grid.x_to_ix(c_point.x)
                iy = self._c_points_grid.y_to_iy(c_point.y)
                self._c_points_grid.update_cell(ix, iy, k, n)
                n += 1
            k += 1
        print('Completed building cpoints grid for {0}'.format(self.name))

    def plot_cpoints(self):
        for c_points_at_k in self.c_points:
            x = [c_point.pose.x for c_point in c_points_at_k]
            y = [c_point.pose.y for c_point in c_points_at_k]
            plt.plot(x, y)
        plt.show()

    def build_obstacle_grid(self):
        from prrt.primitive import get_bounding_box, polygon_contains_point
        assert len(self.c_points) > 0, 'c_points don\'t exist!'
        print('Starting building obstacle grid for {0}'.format(self.name))
        for k in range(len(self.idx_to_alpha)):
            c_points_at_k = self.c_points[k]
            for c_point in c_points_at_k:
                if type(self._vehicle) is ArticulatedVehicle:
                    self._vehicle.phi = c_point.phi
                shape = self._vehicle.get_vertices_at_pose(c_point.pose)
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
                            self.obstacle_grid.update_cell(x_idx, y_idx, k, c_point.d)
                            self.obstacle_grid.update_cell(x_idx - 1, y_idx, k, c_point.d)
                            self.obstacle_grid.update_cell(x_idx, y_idx - 1, k, c_point.d)
                            self.obstacle_grid.update_cell(x_idx - 1, y_idx - 1, k, c_point.d)
            print('{0} out of {1} complete!'.format(k + 1, len(self.idx_to_alpha)))
        print('Completed building obstacle grid for {0}'.format(self.name))

    def inverse_WS2TP(self, p: PoseR2S1, tolerance=0.1) -> (bool, int, float):
        is_exact = True
        if p.y != 0:
            R = (p.x * p.x + p.y * p.y) / (2 * p.y)
            Rmin = abs(self._vehicle.v_max / self._vehicle.w_max)
            if self._K > 0:
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
            d = theta * (abs(R) + self._turning_radius_ref)
            if abs(R) < Rmin:
                is_exact = False
                R = Rmin * np.sign(R)
            a = np.pi * self._vehicle.v_max / (self._vehicle.w_max * R)
            ik = self.alpha2idx(a)
        else:
            if np.sign(p.x) == np.sign(self._K):
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
        assert ik < len(self.c_points), 'ik exceeds limit'
        return is_exact, ik, d

    def get_distance(self, from_pose: PoseR2S1, to_pose: PoseR2S1) -> float:
        to_at_from = to_pose - from_pose
        is_exact, k, d = self.inverse_WS2TP(to_at_from)
        if is_exact:
            return d * self.distance_ref
        else:
            return float('inf')


class ACPTG(CPTG):
    """
        circular PTG for articulated vehicles
    """
    from prrt.vehicle import ArticulatedVehicle

    def __init__(self, size: float, vehicle: ArticulatedVehicle, resolution: float, K: int, init_phi: float):
        self.init_phi = init_phi
        super(ACPTG, self).__init__(size, vehicle, resolution,K)

    def build_cpoints(self):
        """
        Builds a distance map for the given PTG, map size, resolution and vehicle
        """
        k_theta = 1.
        min_dist = 0.015
        turning_radius = 0.1
        print('Starting building cpoints for {0}'.format(self.name))
        for alpha in np.arange(-self._vehicle.alpha_max, self._vehicle.alpha_max + self._alpha_resolution,
                               self._alpha_resolution):
            t = 0.
            n = 0
            v = self._K * self._vehicle.v_max
            self._vehicle.pose = PoseR2S1(0., 0., 0.)
            self._vehicle.phi = self.init_phi
            dist = 0.
            last_pose = PoseR2S1(0, 0, 0)
            w = (alpha / np.pi) * self._vehicle.w_max
            rotation = 0.  # same as pose.theta but defined over the range [0: 2PI)
            self.idx_to_alpha.append(alpha)
            points = []  # type: List[CPoint]
            while abs(rotation) < 1.95 * np.pi and t < self._t_max and dist < self._d_max and n < self._n_max:
                pose = self._vehicle.execute_motion(self._K, w, self._delta_t)
                rotation += w * self._delta_t
                v_tp_space = np.sqrt(v * v + (w * turning_radius) * (w * turning_radius))
                dist += v_tp_space * self._delta_t
                delta_pose = pose - last_pose
                dist1 = delta_pose.norm
                dist2 = abs(delta_pose.theta) * k_theta
                dist_max = max(dist1, dist2)
                t += self._delta_t
                if dist_max > min_dist:
                    points.append(CPoint(pose.copy(), t, dist, v, w, self._vehicle.phi))
                    last_pose.copy_from(pose)
                    n += 1
            self.c_points.append(points)
        print('Completed building cpoints for {0}'.format(self.name))

    def plot(self, alpha: float):
        k = self.alpha2idx(alpha)
        c_points_at_k = self.c_points[k]
        fig, ax = plt.subplots()
        i = 0
        for c_point in c_points_at_k:
            ax.plot(-20, -20)
            ax.plot(20, 20)
            self._vehicle.phi = c_point.phi
            self._vehicle.plot(ax, None, c_point.pose)
            plt.savefig('./out/c_point_at_{0:.0f}_{1:04d}.png'.format(np.rad2deg(alpha), i))
            ax.cla()
            i += 1
