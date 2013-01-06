#include <iwlib.h>



int grab_essid(const char *    ifname,
            char* essid_out)
{
  struct iwreq		wrq;
  char  essid[IW_ESSID_MAX_SIZE + 1];
  unsigned int		i;
  unsigned int		j;
  int			skfd;
  
  skfd = iw_sockets_open();
  /* Make sure ESSID is always NULL terminated */
  memset(essid, 0, sizeof(essid));
  
  /* Get ESSID */
  wrq.u.essid.pointer = (caddr_t) essid;
  wrq.u.essid.length = IW_ESSID_MAX_SIZE + 1;
  wrq.u.essid.flags = 0;
  if(iw_get_ext(skfd, ifname, SIOCGIWESSID, &wrq) < 0){
    return(-1);
    iw_sockets_close(skfd)
   }
  iw_sockets_close(skfd)
  strcpy(essid_out, essid);
}
