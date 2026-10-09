package org.obsidience.tv;

import android.service.notification.NotificationListenerService;

/**
 * An enabled notification listener is what lets an ordinary app read and control
 * other apps' media sessions (MediaSessionManager.getActiveSessions). It reads no
 * notifications; once connected it lets the agent start watching sessions.
 */
public class MediaListener extends NotificationListenerService {
    @Override public void onListenerConnected() {
        AgentService agent = AgentService.instance;
        if (agent != null) agent.main.post(agent::watchSessions);
    }
}
