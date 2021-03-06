#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# =====================================================================================================
# Name: joint_pos_control.py
# Author: Hélio Ochoa
# Version: 0.0
# Description: Computed torque control in the joint space (Gazebo)
# =====================================================================================================

import roslib; roslib.load_manifest('thesis_demo')
import rospy
import sys
import thread

import numpy as np
from numpy.linalg import inv


from sensor_msgs.msg import JointState
from std_msgs.msg import Float64
from controller_manager_msgs.srv import SwitchController
from trajectory_msgs.msg import JointTrajectory
from trajectory_msgs.msg import JointTrajectoryPoint

from urdf_parser_py.urdf import Robot
from pykdl_utils.kdl_kinematics import KDLKinematics


##
# returns robot URDF
# @param urdf URDF object of robot.
def get_urdf_model(Robot):

    def usage():
        print("Tests for kdl_parser:\n")
        print("kdl_parser <urdf file>")
        print("\tLoad the URDF from file.")
        print("kdl_parser")
        print("\tLoad the URDF from the parameter server.")
        sys.exit(1)

    if len(sys.argv) > 2:
        usage()
    if len(sys.argv) == 2 and (sys.argv[1] == "-h" or sys.argv[1] == "--help"):
        usage()
    if (len(sys.argv) == 1):
        robot = Robot.from_parameter_server()
    else:
        f = file(sys.argv[1], 'r')
        robot = Robot.from_xml_string(f.read())
        f.close()

    return robot

##
# Thread to interrupt the loop main
def input_thread(L):
    raw_input("\nPress <ENTER> to interrupt the main loop!\n")
    L.append(None)


class RobotControl(object):
    ##
    # Constructor
    # @param urdf URDF object of robot.
    # @param base_link Name of the root link of the kinematic chain. (robot.get_root())
    # @param end_link Name of the end link of the kinematic chain. ("j2n6s300_end_effector")
    # @param topic_name Name of topic to get the joint states of the robot. ("/j2n6s300/joint_states")
    #
    def __init__(self, urdf, base_link, end_link, topic_name):
        self.urdf = urdf
        self.base_link = base_link
        self.end_link = end_link
        self.topic_name = topic_name
        self.joint_names = None
        self.joint_positions = None
        self.joint_velocities = None
        self.joint_efforts = None
        self.js_idx = None  # Joint state index

        rospy.Subscriber(self.topic_name, JointState, self.get_joint_state)

        # Get info from URDF model
        self.joint_types = []
        for jnt_name in self.get_joint_names():
            jnt = urdf.joint_map[jnt_name]
            self.joint_types.append(jnt.type)

    ##
    # returns a list of the link names in kinematic chain.
    def get_link_names(self, joints=False, fixed=True):
        return self.urdf.get_chain(self.base_link, self.end_link, joints, fixed)

    ##
    # @returns a List of the joint names in the kinematic chain.
    def get_joint_names(self, links=False, fixed=False):
        return self.urdf.get_chain(self.base_link, self.end_link, links=links, fixed=fixed)

    ##
    # Joint states listener callback
    def get_joint_state(self, msg):
        if self.js_idx is None:
            joint_names_list = self.get_joint_names()
            self.js_idx = [msg.name.index(joint_name) for joint_name in joint_names_list]

        self.joint_positions = np.matrix([msg.position[i] for i in self.js_idx])
        self.joint_velocities = np.matrix([msg.velocity[i] for i in self.js_idx])
        self.joint_efforts = np.matrix([msg.effort[i] for i in self.js_idx])

    ##
    # Returns the current joint positions (rad)
    # @param wrapped If False returns the raw encoded positions, if True returns
    #                the angles with the forearm and wrist roll in the range -pi to pi
    def get_joint_positions(self, wrapped=False):
        if self.joint_positions is None:
            rospy.logwarn("\nJoint positions haven't been filled yet.")
            return None
        if wrapped:
            return self.wrap_angles(self.joint_positions)
        else:
            return self.joint_positions

    ##
    # Returns joint angles for continuous joints to a range [0, 2*PI)
    # @param q List of joint positions.
    # @return np.array of wrapped joint positions.
    def wrap_angles(self, q):
        continuous = self.joint_types == 'continuous'
        return np.where(continuous, np.mod(q, 2 * np.pi), q)

    ##
    # Returns the current joint velocities
    def get_joint_velocities(self):
        if self.joint_velocities is None:
            rospy.logwarn("\nJoint velocities haven't been filled yet.")
            return None
        return self.joint_velocities

    ##
    # Returns the current joint efforts
    def get_joint_efforts(self):
        if self.joint_efforts is None:
            rospy.logwarn("\nJoint efforts haven't been filled yet.")
            return None
        return self.joint_efforts


    ##
    # Returns robot kinematics
    def get_jaco_kinematics(self):
        kin = KDLKinematics(self.urdf, self.base_link, self.end_link)
        return kin


    ## TRAJECTORY CONTROL FOR JOINTS
    # Publish the joint commands to move the robot joints
    # @param number of joints(nbJoints)
    def moveJoint(self, jointcmds, nbJoints):
        topic_name = '/j2n6s300/effort_joint_trajectory_controller/command'
        pub = rospy.Publisher(topic_name, JointTrajectory, queue_size=1)
        jointCmd = JointTrajectory()
        point = JointTrajectoryPoint()
        jointCmd.header.stamp = rospy.Time.now() + rospy.Duration.from_sec(0.0)
        point.time_from_start = rospy.Duration.from_sec(5.0)
        for i in range(0, nbJoints):
            jointCmd.joint_names.append('j2n6s300_joint_' + str(i + 1))
            point.positions.append(jointcmds[i])
            point.velocities.append(0)
            point.accelerations.append(0)
            point.effort.append(0)
        jointCmd.points.append(point)
        rate = rospy.Rate(100)
        count = 0
        while count < 500:
            pub.publish(jointCmd)
            count = count + 1
            rate.sleep()

    ## TRAJECTORY CONTROL FOR FINGERS
    # Publish the joint commands to move the fingers
    # @param number of fingers(nbFingers)
    def moveFingers(self, jointcmds, nbFingers):
        topic_name = '/j2n6s300/effort_finger_trajectory_controller/command'
        pub = rospy.Publisher(topic_name, JointTrajectory, queue_size=1)
        jointCmd = JointTrajectory()
        point = JointTrajectoryPoint()
        jointCmd.header.stamp = rospy.Time.now() + rospy.Duration.from_sec(0.0)
        point.time_from_start = rospy.Duration.from_sec(5.0)
        for i in range(0, nbFingers):
            jointCmd.joint_names.append('j2n6s300_joint_finger_' + str(i + 1))
            point.positions.append(jointcmds[i])
            point.velocities.append(0)
            point.accelerations.append(0)
            point.effort.append(0)
        jointCmd.points.append(point)
        rate = rospy.Rate(100)
        count = 0
        while count < 100:
            pub.publish(jointCmd)
            count = count + 1
            rate.sleep()


    ##
    #  ============================= Switch controllers  =============================
    def switchController(self, flag):
        rospy.wait_for_service('/j2n6s300/controller_manager/switch_controller')
        try:
            switch_controller = rospy.ServiceProxy('/j2n6s300/controller_manager/switch_controller', SwitchController)

            if flag == 1:
                ## Switch to torque controller
                switch_controller(['joint_1_torque_controller',
                                   'joint_2_torque_controller',
                                   'joint_3_torque_controller',
                                   'joint_4_torque_controller',
                                   'joint_5_torque_controller',
                                   'joint_6_torque_controller',
                                   'finger_1_position_controller',
                                   'finger_2_position_controller',
                                   'finger_3_position_controller'],
                                  ['effort_joint_trajectory_controller',
                                   'effort_finger_trajectory_controller'], 1)

                print("\nTORQUE CONTROLLER MODE!")

            if flag == 0:
                ## Switch to position controller
                switch_controller(['effort_joint_trajectory_controller',
                                   'effort_finger_trajectory_controller'],
                                  ['joint_1_torque_controller',
                                   'joint_2_torque_controller',
                                   'joint_3_torque_controller',
                                   'joint_4_torque_controller',
                                   'joint_5_torque_controller',
                                   'joint_6_torque_controller',
                                   'finger_1_position_controller',
                                   'finger_2_position_controller',
                                   'finger_3_position_controller'], 1)

                print("\nTRAJECTORY CONTROLLER MODE!")


        except rospy.ServiceException, e:
            print "Service call failed: %s" % e

    ## TORQUE CONTROL
    # Publish the joint torque
    # @param jointCmds - joint commands
    # @param fingerCmds - finger commands (open/.../close)
    def publishTorqueCmd(self, jointCmds, fingerCmds):

        # Define publishers for each joint controller.
        pub1 = rospy.Publisher('/j2n6s300/joint_1_torque_controller/command', Float64, queue_size=1)
        pub2 = rospy.Publisher('/j2n6s300/joint_2_torque_controller/command', Float64, queue_size=1)
        pub3 = rospy.Publisher('/j2n6s300/joint_3_torque_controller/command', Float64, queue_size=1)
        pub4 = rospy.Publisher('/j2n6s300/joint_4_torque_controller/command', Float64, queue_size=1)
        pub5 = rospy.Publisher('/j2n6s300/joint_5_torque_controller/command', Float64, queue_size=1)
        pub6 = rospy.Publisher('/j2n6s300/joint_6_torque_controller/command', Float64, queue_size=1)

        self.jointCmd = [Float64().data, Float64().data, Float64().data, Float64().data, Float64().data, Float64().data]
        self.jointCmd = jointCmds
        pub1.publish(self.jointCmd[0])
        pub2.publish(self.jointCmd[1])
        pub3.publish(self.jointCmd[2])
        pub4.publish(self.jointCmd[3])
        pub5.publish(self.jointCmd[4])
        pub6.publish(self.jointCmd[5])

        # Define publishers for each finger controller.
        pub7 = rospy.Publisher('/j2n6s300/finger_1_position_controller/command', Float64, queue_size=1)
        pub8 = rospy.Publisher('/j2n6s300/finger_2_position_controller/command', Float64, queue_size=1)
        pub9 = rospy.Publisher('/j2n6s300/finger_3_position_controller/command', Float64, queue_size=1)

        self.fingerCmd = [Float64().data, Float64().data, Float64().data]
        self.fingerCmd = fingerCmds
        pub7.publish(self.fingerCmd[0])
        pub8.publish(self.fingerCmd[1])
        pub9.publish(self.fingerCmd[2])

    ##
    # Returns the position desired for a trajectory line
    # @param line start point
    # @param line end point
    # @param step time(t) -> t:[0, 1]
    def trajectory_line(self, line_start_point, line_end_point, alpha):

        position_d = line_start_point*(1 - alpha) + line_end_point*alpha
        return position_d

    ##
    # Returns the position desired for a polynomial 3 trajectory
    # @param initial position (pos_i)
    # @param final position (pos_f)
    # @param initial time(ti), final time(tf) and the time to finish the trajectory
    def polynomial3(self, pos_i, pos_f, ti, tf, t):

        pos_d = pos_i + ((3*(pos_f-pos_i)*(t-ti)**2)/(tf-ti)**2) - (2*(pos_f-pos_i)*(t-ti)**3)/(tf-ti)**3
        return pos_d


def main():
    rospy.init_node('joint_position_control')

    robot = get_urdf_model(Robot)
    base_link = robot.get_root()
    end_link = "j2n6s300_end_effector"
    topic_name = "/j2n6s300/joint_states"
    arm = RobotControl(robot, base_link, end_link, topic_name)
    kin = arm.get_jaco_kinematics()
    rospy.sleep(2)

    ## Switch to torque controller
    arm.switchController(flag=1)

    # =================================================================================================
    # KST FILE
    # =================================================================================================
    path = '/home/ochoa/kst_thesis/joint_pos_control.txt'
    file = open(path, "w")
    line1 = [' t; ',
             'q1; ', 'q1d; ', 'q2; ', 'q2d; ', 'q3; ', 'q3d;', 'q4; ', 'q4d; ', 'q5; ', 'q5d; ', 'q6; ', 'q6d; ',
             'v1; ', 'v1d; ', 'v2; ', 'v2d; ', 'v3; ', 'v3d;', 'v4; ', 'v4d; ', 'v5; ', 'v5d; ', 'v6; ', 'v6d', '\n']
    line2 = [' s; ',
             'rad; ', 'rad; ', 'rad; ', 'rad; ', 'rad; ', 'rad; ', 'rad; ', 'rad; ', 'rad; ', 'rad; ', 'rad; ', 'rad; ',
             'rad/s; ', 'rad/s; ', 'rad/s; ', 'rad/s; ', 'rad/s; ', 'rad/s; ', 'rad/s; ', 'rad/s; ', 'rad/s; ', 'rad/s; ', 'rad/s; ', 'rad/s', '\n']
    file.writelines(line1)
    file.writelines(line2)

    # =================================================================================================
    # Initial Conditions
    # =================================================================================================
    # HOME(rad)
    home = np.matrix([[4.8046852], [2.92482], [1.002], [4.2031852], [1.4458], [1.3233]])
    q_desired = home                                          # desired joint position

    dq_desired = np.transpose(np.matrix([0, 0, 0, 0, 0, 0]))  # desired joint velocity

    d2q_desired = np.transpose(np.matrix([0, 0, 0, 0, 0, 0])) # desired joint acceleration

    dt = 0.01  # integration interval
    error_sum = 0  # error sum

    # =================================================================================================
    # Initial Trajectory Conditions
    # =================================================================================================
    t = 0
    t1 = 0
    t2 = 0
    ti = 0
    tf = 15

    qi = home
    qf = np.transpose(np.matrix([3.1415, 3.1415, 3.1415, 3.1415, 3.1415, 3.1415]))
    q_last = np.transpose(np.matrix([0, 0, 0, 0, 0, 0]))


    # =================================================================================================
    # main loop
    # =================================================================================================
    duration_sec = 200
    count = 0
    rate = rospy.Rate(100)  # 100Hz
    L = []
    thread.start_new_thread(input_thread, (L,))
    while count < 100*duration_sec:
        count = count + 1

        q = np.transpose(arm.get_joint_positions(wrapped=False))   # Current joint positions (rad)
        dq = np.transpose(arm.get_joint_velocities())             # Current joint velocities (rad/s)

        g = np.transpose(np.matrix(kin.gravity(q)))  # gravity matrix

        M = kin.inertia(q)  # joint space mass matrix at the end_link

        # =============================================================================================
        # Trajectory
        # =============================================================================================
        if count > 1000:
            # Polynomial trajectory
            if t <= tf:
                q_desired = arm.polynomial3(qi, qf, ti, tf, t)
                t = t + 0.01

        if (count > 3000) and (count < 8000) :
            ## Sinusoidal equations
            A = np.pi/6  # Amplitude
            T = 8  # Period(s)
            wr = 2*np.pi/T  # resonance frequency
            pos_objective = np.transpose(np.matrix([3.1415, 3.1415, 3.1415, 3.1415, 3.1415, 3.1415]))
            q_desired = np.add(pos_objective, np.transpose(np.matrix([A*np.sin(wr*t1),
                                                                      A*np.sin(wr*t1),
                                                                      A*np.sin(wr*t1),
                                                                      A*np.sin(wr*t1),
                                                                      A*np.sin(wr*t1),
                                                                      A*np.sin(wr*t1)])))
            q_last = q_desired
            t1 = t1 + 0.01


        if count > 8000:
            # Polynomial trajectory
            if t2 <= tf:
                qi2 = q_last
                qf2 = np.transpose(np.matrix([4.8046852, 2.92482, 1.002, 4.2031852, 1.4458, 1.3233]))
                q_desired = arm.polynomial3(qi2, qf2, ti, tf, t2)
                t2 = t2 + 0.01


        # =============================================================================================
        # Controller Gains
        # =============================================================================================
        # Natural frequency (wn)
        wn1 = 16
        wn2 = 10
        wn3 = 10
        wn4 = 20
        wn5 = 20
        wn6 = 20

        kp = np.transpose(np.matrix([wn1**2, wn2**2, wn3**2, wn4**2, wn5**2, wn6**2]))
        kd = np.transpose(np.matrix([2*wn1, 2*wn2, 2*wn3, 2*wn4, 2*wn5, 2*wn6]))
        ki = np.transpose(np.matrix([0.005, 0.005, 0.005, 0.005, 0.005, 0.005]))


        # =============================================================================================
        # Position control in the joint space
        # =============================================================================================
        # velocity error
        delta_velocity = np.subtract(dq_desired, dq)
        aux1 = np.multiply(kd, delta_velocity)

        # position error
        delta_position = np.subtract(q_desired, q)  # position error
        aux2 = np.multiply(kp, delta_position)

        error_sum += delta_position*dt
        aux3 = np.multiply(ki, error_sum)

        w = d2q_desired + aux1 + aux2 + aux3

        # Command Torques (tau)
        tau = M*w + g

        joint_torque = [tau.item(0), tau.item(1), tau.item(2), tau.item(3), tau.item(4), tau.item(5)]
        finger_position = [0, 0, 0]  # Gripper Open
        # finger_position = [1, 1, 1]   # Gripper Close
        arm.publishTorqueCmd(joint_torque, finger_position)


        # =============================================================================================
        # SEND TO FILE
        # =============================================================================================
        TIME = count * 0.010
        # Current joint position
        q1 = q.item(0)
        q2 = q.item(1)
        q3 = q.item(2)
        q4 = q.item(3)
        q5 = q.item(4)
        q6 = q.item(5)

        # Desired joint position
        q1d = q_desired.item(0)
        q2d = q_desired.item(1)
        q3d = q_desired.item(2)
        q4d = q_desired.item(3)
        q5d = q_desired.item(4)
        q6d = q_desired.item(5)

        # Current joint velocity
        v1 = dq.item(0)
        v2 = dq.item(1)
        v3 = dq.item(2)
        v4 = dq.item(3)
        v5 = dq.item(4)
        v6 = dq.item(5)

        # Desired joint velocity
        v1d = dq_desired.item(0)
        v2d = dq_desired.item(1)
        v3d = dq_desired.item(2)
        v4d = dq_desired.item(3)
        v5d = dq_desired.item(4)
        v6d = dq_desired.item(5)

        lines = ' ' + str(TIME) + '; ' \
                + str(q1) + '; ' + str(q1d) + '; ' + str(q2) + '; ' + str(q2d) + '; ' + str(q3) + '; ' + str(q3d) + '; ' + str(q4) + '; ' + str(q4d) + '; ' + str(q5) + '; ' + str(q5d) + '; ' + str(q6) + '; ' + str(q6d) + '; ' \
                + str(v1) + '; ' + str(v1d) + '; ' + str(v2) + '; ' + str(v2d) + '; ' + str(v3) + '; ' + str(v3d) + '; ' + str(v4) + '; ' + str(v4d) + '; ' + str(v5) + '; ' + str(v5d) + '; ' + str(v6) + '; ' + str(v6d)
        file.write(lines + '\n')

        rate.sleep()
        if L:
            break

    file.close()

    # =============================================================================================
    # PRINTS
    # =============================================================================================
    print '\n ------------------------------------------------------------------------------------------------------------------------------------'
    print '\nPosition error:', delta_position
    print '\nTau:', joint_torque
    rospy.loginfo("I will publish to the topics %d", count)
    print '\n ------------------------------------------------------------------------------------------------------------------------------------'

    ## Switch to position controller
    arm.switchController(flag=0)

    # home robot
    home = [4.8046852, 2.92482, 1.002, 4.2031852, 1.4458, 1.3233]
    nbJoints = 6
    nbfingers = 3
    arm.moveJoint(home, nbJoints)
    arm.moveFingers([0, 0, 0], nbfingers)
    print('\nRobot has returned to HOME...')

if __name__ == '__main__':
    try:
        main()

    except rospy.ROSInterruptException:
        pass
