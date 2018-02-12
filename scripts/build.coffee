# Description:
#   Build CARLA from hubot.
#
# Dependencies:
#   "child_process": ">= 0.0.0"
#
# Commands:
#   hubot build <branch> - Build GitHub <branch> of CARLA
#   hubot jobs - Show queued jobs
#   hubot cancel #ID - Cancel the job #ID
#

exec = require('child_process').exec

queue_size = 4

exec_command = "/usr/bin/env python3 ./builder/carla_builder.py -b %"

start_message = "Building branch `%branch` from GitHub, I will notify you when it's done :slightly_smiling_face:"
end_message = "Build job #% finished."
error_message = "Ooops, something went wrong!\n```\n%\n```"
busy_message = ":grimacing: I'm currently busy, I will notify you when your build starts!"
queue_is_full = ":dizzy_face: The build queue is full!"

module.exports = (robot) ->

  robot.brain.data.build_queue = [] if !robot.brain.data.build_queue

  robot.respond /build(\s*)$/i, (res) ->
    res.send "Please specify which branch you want to build.\nbuild <branch>"

  robot.respond /build (\S+)/i, (res) ->
    jobid = robot.brain.get('build_job_count') * 1 or 1
    robot.brain.set 'build_job_count', jobid + 1
    robot.emit 'build_request', {
      'jobid': jobid,
      'res': res,
      'branch': res.match[1],
      'status': 'requested'
    }

  robot.respond /cancel (?:job )?(?:#)?(\d+)/i, (res) ->
    id = res.match[1] * 1
    console.log 'cancelling job #' + id + ' as requested by *' + res.message.user.name + '*'
    for item in robot.brain.data.build_queue
      if item['jobid'] == id
        if item['status'] == 'in_progress'
          res.send ':hand: cannot cancel job #' + id + ', is already in progress'
          return
        item['status'] = 'cancelled'
        message = 'job #' + id + ' cancelled'
        if res.message.user != item['res'].message.user
          message += ' by *' + res.message.user.name + '*'
        item['res'].reply message
        return
    res.send ':dizzy_face: job #' + id + ' not found!'

  robot.respond /(jobs|show( me)?( the)?( build(ing)?| job(s)?)? queue)/i, (res) ->
    if robot.brain.data.build_queue.length < 1
      res.send 'The queue is empty.'
      return
    msgs = ['Showing you the list of pending jobs\n']
    for item in robot.brain.data.build_queue
      msg = ''
      if item['status'] == 'in_progress'
        msg += ':arrow_forward:'
      else if item['status'] == 'cancelled'
        msg += ':no_entry:'
      else
        msg += ':double_vertical_bar:'
      msg += ' #' + item['jobid']
      msg += ': branch `' + item['branch']
      msg += '` by *' + item['res'].message.user.name + '*'
      msgs.push msg
    res.send msgs.join('\n')

  robot.on 'build_request', (job) ->
    count_active = 0
    for item in robot.brain.data.build_queue
      if item['status'] != 'cancelled'
        count_active += 1
    if count_active >= queue_size
      job['res'].send queue_is_full
      job['status'] = 'cancelled'
      return
    bip = robot.brain.data.build_queue[0]
    if bip and bip['status'] == 'in_progress'
      job['res'].reply busy_message
    job['status'] = 'queued'
    robot.brain.data.build_queue.push job
    robot.emit '_trigger_build', 'build_request'

  robot.on 'build_finished', (job) ->
    if job['stderr']
      job['res'].reply error_message.replace "%", job['stderr']
    else
      msg = end_message.replace "%", job['jobid']
      if job['stderr']
        error_message = job['stderr']
      else
        error_message = job['stdout']
      job['res'].reply [msg, error_message].join('\n')

  robot.on '_trigger_build', (reason) ->
    bip = robot.brain.data.build_queue[0]
    if !bip
      return
    if bip['status'] == 'in_progress'
      return
    if bip['status'] == 'cancelled'
      robot.brain.data.build_queue.shift()
      robot.emit '_trigger_build', 'build_cancelled'
      return
    bip['status'] = 'in_progress'
    # Do the build here.
    res = bip['res']
    branch = bip['branch']
    res.reply start_message.replace "%branch", branch
    command = exec_command.replace "%", branch
    console.log 'building branch "' + branch + '" as requested by ' + res.message.user.name
    exec command, (error, stdout, stderr) ->
      bip['error'] = error
      bip['stdout'] = stdout
      bip['stderr'] = stderr
      robot.brain.data.build_queue.shift()
      bip['in_progress'] = false
      robot.emit 'build_finished', bip
      robot.emit '_trigger_build', 'build_finished'
